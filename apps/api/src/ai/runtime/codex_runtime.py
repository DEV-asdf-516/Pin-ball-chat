import asyncio
import json
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Callable

from ai.errors import EmptyOutputError, ProviderErrorCode, ProviderRuntimeError, ProviderTimeoutError, runtime_error_factory, timeout_error_factory
from ai.protocol.codex_protocol import CodexTurnStateMachine, _PROHIBITED_SERVER_REQUESTS, classify_event_error, is_secure_thread, parse_turn_start, validate_model_page
from ai.runtime.queue import BoundedRuntimeQueue, RuntimeQueueClosed
from ai.runtime.util import RUNTIME_UMASK, AsyncOnce, GenerationGate, drain_stderr, reap_process_group, run_subprocess_capture, runtime_env
from ai.settings import CODEX_COMMAND, CODEX_MAX_IN_FLIGHT, CODEX_RUNTIME_VERSION, PINBALLCHAT_RUNTIME_ROOT, RUNTIME_FIRST_DELTA_TIMEOUT, RUNTIME_IDLE_TIMEOUT, RUNTIME_INTERRUPT_GRACE_SECONDS, RUNTIME_QUEUE_BLOCK_SECONDS, RUNTIME_QUEUE_SIZE, RUNTIME_RESTART_BACKOFF_SECONDS
from ai.specs import GenerateRequest, ProviderName
from util.safe_util import get_safe_dict


_COMMAND = CODEX_COMMAND
_VERSION = CODEX_RUNTIME_VERSION
_RUNTIME_ROOT = Path(PINBALLCHAT_RUNTIME_ROOT)
_TURN_TOMBSTONE_MAXLEN = 256
log = logging.getLogger(__name__)


@dataclass
class _TurnRoute:
    # turn_id 하나의 라우팅 수명주기. router가 turn/completed를 보면 terminal_seen을
    # 올리고 queue를 close()한다; consumer(stream())가 자기 finally에서 consumer_done을
    # 올린다. 두 플래그는 서로 독립적이다 — 정상 완료/확인된 interrupt는 항상
    # terminal_seen이 먼저지만, 에러로 소비자가 먼저 빠져나가는 경로(현재 crash 처리,
    # T4에서 정리 예정)에서는 순서가 반대일 수 있어 단순 선형 상태로는 표현할 수 없다.
    queue: BoundedRuntimeQueue
    terminal_seen: bool = False
    consumer_done: bool = False


def _runtime_env() -> dict[str, str]:
    env = runtime_env("codex-home")
    env["CODEX_HOME"] = env["HOME"]
    return env


_runtime_error : Callable[..., ProviderRuntimeError] = runtime_error_factory(ProviderName.OPENAI_CODEX)
_timeout_error: Callable[..., ProviderTimeoutError] = timeout_error_factory(ProviderName.OPENAI_CODEX)
_event_error = classify_event_error


class CodexAppServer:
    def __init__(self):
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future] = {}
        self._ignored_response_ids: set[int] = set()
        self._turn_routes: dict[str, _TurnRoute] = {}
        self._turn_tombstones: OrderedDict[str, None] = OrderedDict()
        self._early_turn_events: dict[str, list[dict]] = {}
        self._start_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._generation_gate = GenerationGate(CODEX_MAX_IN_FLIGHT)
        self._preflight_cache: AsyncOnce[str] = AsyncOnce()
        self._crash_error: ProviderRuntimeError | None = None
        self._last_crash_at = 0.0
        self._cleanup_tasks: set[asyncio.Task] = set()
        self._on_login_completed: Callable[[bool], None] = lambda success: None
        self._on_crash: Callable[[ProviderErrorCode | str], None] = lambda code: None

    def bind_login_hooks(self, on_completed: Callable[[bool], None], on_crash: Callable[[ProviderErrorCode | str], None]) -> None:
        self._on_login_completed = on_completed
        self._on_crash = on_crash

    # auth 계층 전용 좁은 API. stream 경로는 계속 private을 직접 쓴다.
    async def ensure_started(self, phase: str) -> None:
        await self._start(phase)

    async def rpc(self, method: str, params: dict, timeout: float, phase: str) -> dict:
        return await self._timed_request(method, params, timeout, phase)

    async def raw_request(self, method: str, params: dict) -> dict:
        # 오직 auth._expire_login의 cancel 경로용.
        return await self._request(method, params)

    async def terminate(self) -> None:
        await self._terminate_runtime()

    @property
    def has_active_turns(self) -> bool:
        return self._generation_gate.has_active

    def _tombstone_turn(self, turn_id: str) -> None:
        self._turn_tombstones[turn_id] = None
        self._turn_tombstones.move_to_end(turn_id)
        while len(self._turn_tombstones) > _TURN_TOMBSTONE_MAXLEN:
            self._turn_tombstones.popitem(last=False)

    def _maybe_remove_route(self, turn_id: str) -> None:
        route = self._turn_routes.get(turn_id)
        if route and route.terminal_seen and route.consumer_done:
            del self._turn_routes[turn_id]
            self._tombstone_turn(turn_id)

    async def _preflight(self, phase: str = "first_delta") -> str:
        async def _run_preflight() -> str:
            try:
                output = await run_subprocess_capture(_COMMAND, "--version", env=_runtime_env(), timeout=RUNTIME_FIRST_DELTA_TIMEOUT, grace_seconds=RUNTIME_INTERRUPT_GRACE_SECONDS)
            except FileNotFoundError as exc:
                raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "codex runtime is not installed") from exc
            except TimeoutError as exc:
                raise _timeout_error("Codex runtime preflight timed out", phase=phase) from exc
            version = output.stdout.decode(errors="replace").strip()
            if output.returncode or version != f"codex-cli {_VERSION}":
                raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "codex runtime version is incompatible")
            return version
        return await self._preflight_cache.get(_run_preflight)

    async def version(self) -> str:
        return await self._preflight()

    async def _start(self, phase: str = "first_delta") -> None:
        async with self._start_lock:
            if self._process and self._process.returncode is None and self._crash_error is None:
                return
            if self._process and self._process.returncode is None:
                await self._terminate_runtime(self._crash_error)
            remaining_backoff = RUNTIME_RESTART_BACKOFF_SECONDS - (time.monotonic() - self._last_crash_at)
            if remaining_backoff > 0:
                await asyncio.sleep(remaining_backoff)
            await self._preflight(phase)
            self._crash_error = None
            try:
                self._process = await asyncio.create_subprocess_exec(
                    _COMMAND, "app-server", "--stdio", stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE, cwd=str(_RUNTIME_ROOT / "scratch"), env=_runtime_env(), start_new_session=True, umask=RUNTIME_UMASK,
                )
            except FileNotFoundError as exc:
                raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "codex runtime is not installed") from exc
            process = self._process
            self._reader_task = asyncio.create_task(self._read_events(process))
            self._stderr_task = asyncio.create_task(drain_stderr(process.stderr, "codex"))
            try:
                await self._timed_request("initialize", {"clientInfo": {"name": "pinballchat", "version": "0.1.0"}, "capabilities": {"experimentalApi": False}}, RUNTIME_FIRST_DELTA_TIMEOUT, phase)
                await self._cleanup_persisted_threads()
            except asyncio.CancelledError:
                await self._terminate_runtime()
                raise
            except Exception:
                await self._terminate_runtime()
                raise

    async def _read_events(self, process: asyncio.subprocess.Process) -> None:
        reached_eof = False
        try:
            assert process.stdout
            while line := await process.stdout.readline():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    await self._crash(_runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "codex runtime emitted malformed JSON"))
                    return
                if not isinstance(event, dict):
                    await self._crash(_runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "codex runtime emitted a malformed message"))
                    return
                if "id" in event and "method" in event:
                    method = event.get("method")
                    error = _runtime_error(
                        ProviderErrorCode.PROVIDER_CONTRACT_VIOLATION if method in _PROHIBITED_SERVER_REQUESTS else ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE,
                        "Codex attempted a prohibited tool action" if method in _PROHIBITED_SERVER_REQUESTS else "codex runtime emitted an unsupported server request",
                    )
                    await self._crash(error)
                    asyncio.create_task(self._terminate_runtime(error))
                    return
                if "id" in event:
                    request_id = event["id"]
                    if request_id in self._ignored_response_ids:
                        self._ignored_response_ids.discard(request_id)
                        continue
                    future = self._pending.pop(request_id, None)
                    if future is None:
                        await self._crash(_runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "codex runtime returned an unknown response ID"))
                        return
                    if future.cancelled():
                        continue
                    if event.get("error"):
                        future.set_exception(_event_error(event))
                    elif isinstance(event.get("result"), dict):
                        future.set_result(event["result"])
                    else:
                        future.set_exception(_runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "codex runtime returned malformed response"))
                    continue
                method = event.get("method")
                params = event.get("params")
                if not isinstance(method, str) or not isinstance(params, dict):
                    await self._crash(_runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "codex runtime emitted malformed notification"))
                    return
                if method == "account/login/completed":
                    if not isinstance(params.get("success"), bool):
                        error = _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "codex runtime emitted a malformed login completion")
                        await self._crash(error)
                        asyncio.create_task(self._terminate_runtime(error))
                        return
                    self._on_login_completed(params.get("success") is True)
                    continue
                completed_turn = get_safe_dict(params, "turn")
                turn_id = params.get("turnId") or completed_turn.get("id")
                route = self._turn_routes.get(turn_id) if isinstance(turn_id, str) else None
                if route:
                    try:
                        accepted = await route.queue.try_put(event)
                    except RuntimeQueueClosed:
                        # 이미 닫힌 route로 늦게 도착한 이벤트 — 무해하게 무시하고 라우팅 계속.
                        accepted = None
                    if accepted is False:
                        # overflow. Codex router는 절대 blocking put()을 쓰지 않는다 — 한 turn의
                        # 느린 consumer가 공용 reader를 막으면 다른 모든 turn까지 함께 멈추기
                        # 때문이다. turn 단위로만 격리(interrupt)하는 대신 공용 runtime 상태를
                        # 확실히 복구할 방법이 없으므로, 여기서는 runtime 전체를 종료한다.
                        error = _runtime_error(ProviderErrorCode.PROVIDER_TIMEOUT, "Codex event queue was blocked", retryable=True, phase="idle")
                        await route.queue.fail(error)
                        await self._crash(error)
                        asyncio.create_task(self._terminate_runtime(error))
                        return
                    if accepted and method == "turn/completed":
                        route.terminal_seen = True
                        await route.queue.close()
                elif isinstance(turn_id, str) and turn_id in self._turn_tombstones:
                    # 이미 종료 처리된 turn의 late event — 재버퍼링하지 않고 무시.
                    log.debug("ignoring late Codex event for tombstoned turn=%s method=%s", turn_id, method[:120])
                elif isinstance(turn_id, str):
                    buffered = self._early_turn_events.setdefault(turn_id, [])
                    buffered_count = sum(len(events) for events in self._early_turn_events.values())
                    if buffered_count >= RUNTIME_QUEUE_SIZE:
                        await self._crash(_runtime_error(ProviderErrorCode.PROVIDER_TIMEOUT, "Codex event queue was blocked", retryable=True, phase="idle"))
                        asyncio.create_task(self._terminate_runtime())
                        return
                    buffered.append(event)
                else:
                    log.debug("ignored Codex notification method=%s", method[:120])
            reached_eof = True
        except asyncio.CancelledError:
            raise
        finally:
            if self._process is process:
                if reached_eof or process.returncode is not None:
                    await self._crash(_runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_CRASHED, "codex runtime exited unexpectedly", retryable=True))
                if self._crash_error and process.returncode is None:
                    asyncio.create_task(self._terminate_runtime(self._crash_error))

    async def _crash(self, error: ProviderRuntimeError) -> None:
        if self._crash_error:
            return
        self._crash_error = error
        self._last_crash_at = time.monotonic()
        self._on_crash(error.code)
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        self._pending.clear()
        # 각 in-flight route에 에러를 즉시 전달(pending delta 폐기 + waiter 깨우기는
        # queue.fail()이 대신한다)하고, route 자체도 정리해 tombstone으로 넘긴다 — 크래시
        # 후에는 consumer가 정상적으로 CONSUMER_DONE에 도달하길 기다릴 이유가 없다.
        for turn_id, route in list(self._turn_routes.items()):
            await route.queue.fail(error)
            del self._turn_routes[turn_id]
            self._tombstone_turn(turn_id)
        self._early_turn_events.clear()

    async def _request(self, method: str, params: dict) -> dict:
        process = self._process
        if not process or process.returncode is not None or not process.stdin:
            raise self._crash_error or _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_CRASHED, "codex runtime is not running", retryable=True)
        loop = asyncio.get_running_loop()
        async with self._write_lock:
            request_id = self._next_id
            self._next_id += 1
            future = loop.create_future()
            self._pending[request_id] = future
            try:
                process.stdin.write((json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}) + "\n").encode())
                await process.stdin.drain()
            except asyncio.CancelledError:
                if self._pending.pop(request_id, None) is not None:
                    self._ignored_response_ids.add(request_id)
                raise
            except (BrokenPipeError, ConnectionResetError) as exc:
                self._pending.pop(request_id, None)
                error = _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_CRASHED, "codex runtime pipe closed", retryable=True)
                await self._crash(error)
                asyncio.create_task(self._terminate_runtime(error))
                raise error from exc
        try:
            return await future
        except asyncio.CancelledError:
            if self._pending.pop(request_id, None) is not None:
                self._ignored_response_ids.add(request_id)
            raise

    async def _timed_request(self, method: str, params: dict, timeout: float, phase: str) -> dict:
        try:
            return await asyncio.wait_for(self._request(method, params), timeout=timeout)
        except TimeoutError as exc:
            await self._terminate_runtime()
            raise _timeout_error(f"Codex {method} timed out", phase=phase) from exc

    async def _cleanup_persisted_threads(self) -> None:
        try:
            cursor: str | None = None
            while True:
                result = await asyncio.wait_for(self._request("thread/list", {"cursor": cursor} if cursor else {}), timeout=RUNTIME_INTERRUPT_GRACE_SECONDS)
                threads = result.get("data") or result.get("threads") or []
                for thread in threads:
                    if isinstance(thread, dict) and thread.get("id") and not thread.get("ephemeral"):
                        try:
                            await asyncio.wait_for(self._request("thread/delete", {"threadId": thread["id"]}), timeout=RUNTIME_INTERRUPT_GRACE_SECONDS)
                        except Exception:
                            log.warning("Codex persisted thread cleanup failed")
                cursor = result.get("nextCursor")
                if not isinstance(cursor, str) or not cursor:
                    return
        except Exception:
            log.warning("Codex startup thread cleanup failed")

    async def startup_cleanup(self) -> None:
        await self._start()

    async def list_models(self) -> list[str]:
        await self._start()
        models: list[str] = []
        cursor: str | None = None
        while True:
            result = await self._timed_request("model/list", {"cursor": cursor} if cursor else {}, RUNTIME_FIRST_DELTA_TIMEOUT, "first_delta")
            models.extend(validate_model_page(result))
            cursor = result.get("nextCursor")
            if not cursor:
                return list(dict.fromkeys(models))

    async def _cleanup_thread(self, thread_id: str, persisted: bool) -> None:
        try:
            await asyncio.wait_for(self._request("thread/unsubscribe", {"threadId": thread_id}), timeout=RUNTIME_INTERRUPT_GRACE_SECONDS)
        except Exception:
            pass
        if persisted:
            try:
                await asyncio.wait_for(self._request("thread/delete", {"threadId": thread_id}), timeout=RUNTIME_INTERRUPT_GRACE_SECONDS)
            except Exception:
                pass

    def _schedule_thread_cleanup(self, thread_id: str, persisted: bool) -> None:
        task = asyncio.create_task(self._cleanup_thread(thread_id, persisted))
        self._cleanup_tasks.add(task)
        task.add_done_callback(self._cleanup_tasks.discard)

    async def _interrupt(self, thread_id: str, turn_id: str, queue: BoundedRuntimeQueue) -> None:
        deadline = time.monotonic() + RUNTIME_INTERRUPT_GRACE_SECONDS

        def remaining() -> float:
            return max(0.001, deadline - time.monotonic())

        try:
            await asyncio.wait_for(self._request("turn/interrupt", {"threadId": thread_id, "turnId": turn_id}), timeout=remaining())
            while True:
                event = await queue.get(timeout=remaining())
                params = event.get("params", {})
                completed = get_safe_dict(params, "turn")
                if event.get("method") == "turn/completed" and (params.get("turnId") or completed.get("id")) == turn_id:
                    status = params.get("status")
                    if isinstance(params.get("turn"), dict):
                        status = params["turn"].get("status")
                    if status != "interrupted":
                        raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "Codex interrupt did not complete as interrupted")
                    return
        except Exception as exc:
            await self._terminate_runtime()
            if isinstance(exc, ProviderRuntimeError):
                raise exc
            raise _timeout_error("Codex interrupt timed out", phase="interrupt") from exc

    async def _terminate_runtime(self, error: ProviderRuntimeError | None = None) -> None:
        process = self._process
        if process and process.returncode is None:
            await reap_process_group(process, RUNTIME_INTERRUPT_GRACE_SECONDS)
        if self._process is not process:
            return
        await self._crash(error or _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_CRASHED, "codex runtime was terminated", retryable=True))
        self._ignored_response_ids.clear()
        if self._process is process:
            self._process = None

    async def shutdown(self) -> None:
        if self._cleanup_tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*tuple(self._cleanup_tasks), return_exceptions=True), timeout=RUNTIME_INTERRUPT_GRACE_SECONDS)
            except TimeoutError:
                for task in tuple(self._cleanup_tasks):
                    task.cancel()
        await self._terminate_runtime()
        runtime_tasks = [task for task in (self._reader_task, self._stderr_task) if task]
        for task in runtime_tasks:
            if task and not task.done():
                task.cancel()
        if runtime_tasks:
            await asyncio.gather(*runtime_tasks, return_exceptions=True)
        self._reader_task = None
        self._stderr_task = None

    async def _ensure_session_ready(self, remaining: Callable[[], float]) -> None:
        try:
            await asyncio.wait_for(self._start(), timeout=remaining())
        except TimeoutError as exc:
            await self._terminate_runtime()
            raise _timeout_error("Codex runtime startup timed out", phase="first_delta") from exc
        account_result = await self._timed_request("account/read", {}, remaining(), "first_delta")
        account = get_safe_dict(account_result, "account")
        if account.get("type") != "chatgpt":
            raise _runtime_error(ProviderErrorCode.PROVIDER_AUTH_REQUIRED, "ChatGPT login is required")

    async def _open_secure_thread(self, req: GenerateRequest, remaining: Callable[[], float]) -> tuple[str, bool]:
        thread_params = {
            "cwd": str(_RUNTIME_ROOT / "scratch"), "sandbox": "read-only", "approvalPolicy": "never",
            "ephemeral": True, "allowProviderModelFallback": False, "baseInstructions": req.system, "model": req.model,
        }
        thread_start = await self._timed_request("thread/start", thread_params, remaining(), "first_delta")
        thread = get_safe_dict(thread_start, "thread")
        thread_id = thread.get("id")
        ephemeral = thread.get("ephemeral")
        if not isinstance(ephemeral, bool):
            if isinstance(thread_id, str):
                self._schedule_thread_cleanup(thread_id, True)
            raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "codex thread/start returned no ephemeral state")
        persisted = thread.get("ephemeral") is not True
        if not isinstance(thread_id, str) or not thread_id:
            raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "codex thread/start returned no thread ID")
        if not is_secure_thread(thread_start, req.model, _RUNTIME_ROOT / "scratch"):
            self._schedule_thread_cleanup(thread_id, persisted)
            raise _runtime_error(ProviderErrorCode.PROVIDER_CONTRACT_VIOLATION, "Codex did not apply the required isolated runtime policy")
        return thread_id, persisted

    async def _start_turn(self, thread_id: str, persisted: bool, req: GenerateRequest, remaining: Callable[[], float]) -> str:
        # Older pinned runtimes may not honor ephemeral. The same dedicated-runtime thread is a persisted fallback
        # and is deleted in every exit path below.
        prompt = "\n\n".join(f"{message.role}: {message.content}" for message in req.messages)
        try:
            turn_start = await self._timed_request("turn/start", {"threadId": thread_id, "input": [{"type": "text", "text": prompt}]}, remaining(), "first_delta")
        except Exception:
            self._schedule_thread_cleanup(thread_id, persisted)
            raise
        turn_id = parse_turn_start(turn_start)
        if turn_id is None:
            self._schedule_thread_cleanup(thread_id, persisted)
            raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "codex turn/start returned no turn ID")
        return turn_id

    async def _attach_route(self, turn_id: str) -> tuple[BoundedRuntimeQueue, _TurnRoute]:
        queue: BoundedRuntimeQueue = BoundedRuntimeQueue(maxsize=RUNTIME_QUEUE_SIZE, block_seconds=RUNTIME_QUEUE_BLOCK_SECONDS)
        route = _TurnRoute(queue=queue)
        self._turn_routes[turn_id] = route
        for event in self._early_turn_events.pop(turn_id, []):
            accepted = await queue.try_put(event)
            if not accepted:
                # early-buffer 재생 중 overflow도 런타임 전체 종료로 처리한다 (router의
                # 정상 경로 overflow 처리와 동일한 정책 — 위 route.queue.try_put 분기 참고).
                overflow_error = _runtime_error(ProviderErrorCode.PROVIDER_TIMEOUT, "Codex event queue was blocked", retryable=True, phase="idle")
                await self._crash(overflow_error)
                asyncio.create_task(self._terminate_runtime(overflow_error))
                break
        return queue, route

    async def stream(self, req: GenerateRequest) -> AsyncIterator[str]:
        async with self._generation_gate.acquire():
            first_delta_deadline = time.monotonic() + RUNTIME_FIRST_DELTA_TIMEOUT

            def first_delta_remaining() -> float:
                return max(0.001, first_delta_deadline - time.monotonic())

            await self._ensure_session_ready(first_delta_remaining)
            thread_id, persisted = await self._open_secure_thread(req, first_delta_remaining)
            turn_id = await self._start_turn(thread_id, persisted, req, first_delta_remaining)
            queue, route = await self._attach_route(turn_id)
            machine = CodexTurnStateMachine(turn_id)
            try:
                while not machine.completed:
                    timeout = RUNTIME_IDLE_TIMEOUT if machine.has_emitted else first_delta_remaining()
                    try:
                        event = await queue.get(timeout=timeout)
                    except TimeoutError as exc:
                        await self._interrupt(thread_id, turn_id, queue)
                        raise _timeout_error("Codex generation timed out", phase="idle" if machine.has_emitted else "first_delta") from exc
                    except RuntimeQueueClosed:
                        raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "codex turn route closed unexpectedly")
                    if text := machine.consume_event(event):
                        yield text
            except (GeneratorExit, asyncio.CancelledError):
                try:
                    await self._interrupt(thread_id, turn_id, queue)
                except Exception:
                    pass
                raise
            except ProviderRuntimeError:
                if not machine.terminal_received and self._crash_error is None:
                    try:
                        await self._interrupt(thread_id, turn_id, queue)
                    except Exception:
                        pass
                raise
            finally:
                route.consumer_done = True
                self._maybe_remove_route(turn_id)
                self._early_turn_events.pop(turn_id, None)
                self._schedule_thread_cleanup(thread_id, persisted)
            if not machine.has_emitted:
                raise EmptyOutputError("codex produced no content")


runtime = CodexAppServer()

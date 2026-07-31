import asyncio
import logging
import time
from pathlib import Path
from typing import AsyncIterator, Callable

from ai.errors import EmptyOutputError, ProviderErrorCode, ProviderRuntimeError, ProviderTimeoutError, runtime_error_factory, timeout_error_factory
from ai.protocol.codex_protocol import CodexTurnStateMachine, is_secure_thread, parse_started_turn_id, parse_model_page
from ai.runtime.codex.connection import CodexRpcConnection
from ai.runtime.codex.router import CodexTurnRouter
from ai.runtime.queue import BoundedRuntimeQueue, RuntimeQueueClosed
from ai.runtime.util import RUNTIME_UMASK, AsyncOnce, GenerationGate, drain_stderr, reap_process_group, remaining_seconds, run_subprocess_capture, runtime_env
from ai.settings import CODEX_COMMAND, CODEX_MAX_IN_FLIGHT, CODEX_RUNTIME_VERSION, PINBALLCHAT_RUNTIME_ROOT, RUNTIME_FIRST_DELTA_TIMEOUT, RUNTIME_IDLE_TIMEOUT, RUNTIME_INTERRUPT_GRACE_SECONDS, RUNTIME_RESTART_BACKOFF_SECONDS
from ai.specs import GenerateRequest, ProviderName
from util.safe_util import get_safe_dict


_COMMAND = CODEX_COMMAND
_VERSION = CODEX_RUNTIME_VERSION
_RUNTIME_ROOT = Path(PINBALLCHAT_RUNTIME_ROOT)
log = logging.getLogger(__name__)


def _build_runtime_env() -> dict[str, str]:
    env = runtime_env("codex-home")
    env["CODEX_HOME"] = env["HOME"]
    return env


_runtime_error : Callable[..., ProviderRuntimeError] = runtime_error_factory(ProviderName.OPENAI_CODEX)
_timeout_error: Callable[..., ProviderTimeoutError] = timeout_error_factory(ProviderName.OPENAI_CODEX)


class CodexAppServer:
    def __init__(self):
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task | None = None
        self._connection = CodexRpcConnection()
        self._current_epoch: int = 0
        self._router = CodexTurnRouter()
        self._start_lock = asyncio.Lock()
        self._generation_gate = GenerationGate(CODEX_MAX_IN_FLIGHT)
        self._preflight_cache: AsyncOnce[str] = AsyncOnce()
        self._crash_error: ProviderRuntimeError | None = None
        self._last_crash_at = 0.0
        self._cleanup_tasks: set[asyncio.Task] = set()
        self._on_login_completed: Callable[[bool], None] = lambda success: None
        self._on_crash: Callable[[ProviderErrorCode | str], None] = lambda code: None

    async def _preflight(self, phase: str = "first_delta") -> str:
        async def _run_preflight() -> str:
            try:
                output = await run_subprocess_capture(
                    _COMMAND, "--version",
                    env=_build_runtime_env(),
                    timeout=RUNTIME_FIRST_DELTA_TIMEOUT,
                    grace_seconds=RUNTIME_INTERRUPT_GRACE_SECONDS
                )
            except FileNotFoundError as exc:
                raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "codex runtime is not installed") from exc
            except TimeoutError as exc:
                raise _timeout_error("Codex runtime preflight timed out", phase=phase) from exc

            version = output.stdout.decode(errors="replace").strip()

            if output.returncode or version != f"codex-cli {_VERSION}":
                raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "codex runtime version is incompatible")

            return version

        return await self._preflight_cache.get(_run_preflight)

    async def _on_notification(
        self,
        process: asyncio.subprocess.Process,
        epoch: int,
        event: dict
    ) -> bool:

        method = event.get("method")
        params: dict = event.get("params", {})

        if method == "account/login/completed":
            if not isinstance(params.get("success"), bool):
                await self._abort_connection(process, epoch,
                    _runtime_error(
                        ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE,
                        "codex runtime emitted a malformed login completion"
                    )
                )
                return False

            self._on_login_completed(params.get("success") is True)
            return True

        try:
            await self._router.route_event(event)
        except ProviderRuntimeError as route_error:
            # router는 process terminate를 수행하지 않으므로 facade가 runtime 전체를 crash+terminate한다.
            await self._abort_connection(process, epoch, route_error)
            return False

        return True

    async def _abort_connection(
        self,
        process: asyncio.subprocess.Process,
        epoch: int,
        error: ProviderRuntimeError
    ) -> None:
        if self._process is not process or epoch != self._current_epoch:
            return

        await self._crash(error)

        if process.returncode is None:
            asyncio.create_task(self._terminate_runtime(error, target=process))

    async def _try_cleanup_request(
        self,
        method: str,
        params: dict,
        *,
        warning: str | None = None,
    ) -> dict | None:
        try:
            return await asyncio.wait_for(
                self.call_runtime(method, params),
                timeout=RUNTIME_INTERRUPT_GRACE_SECONDS,
            )
        except Exception:
            if warning:
                log.warning(warning)
            return None

    async def _crash(self, error: ProviderRuntimeError) -> None:
        if self._crash_error:
            return
        self._crash_error = error
        self._last_crash_at = time.monotonic()
        self._on_crash(error.code)
        self._connection.fail_pending(error)
        await self._router.abort_all(error)

    async def _terminate_runtime(
        self,
        error: ProviderRuntimeError | None = None,
        target: asyncio.subprocess.Process | None = None
    ) -> None:
        if target is not None and self._process is not target:
            # 예약된 시점과 실행 시점 사이에 새 process로 재시작됐다 — 새 runtime을 건드리지 않는다.
            return
        process = self._process

        if process and process.returncode is None:
            await reap_process_group(process, RUNTIME_INTERRUPT_GRACE_SECONDS)

        if self._process is not process:
            return

        await self._crash(error or _runtime_error(
            ProviderErrorCode.PROVIDER_RUNTIME_CRASHED,
            "codex runtime was terminated",
            retryable=True
        ))

        if self._process is process:
            self._process = None

    def _schedule_thread_cleanup(self, thread_id: str, persisted: bool) -> None:

        async def cleanup_thread() -> None:
            await self._try_cleanup_request("thread/unsubscribe", {"threadId": thread_id})
            if persisted:
                await self._try_cleanup_request("thread/delete", {"threadId": thread_id})

        task = asyncio.create_task(cleanup_thread())
        self._cleanup_tasks.add(task)
        task.add_done_callback(self._cleanup_tasks.discard)

    async def _interrupt_turn(self, thread_id: str, turn_id: str, queue: BoundedRuntimeQueue) -> None:
        deadline = time.monotonic() + RUNTIME_INTERRUPT_GRACE_SECONDS

        try:
            await asyncio.wait_for(
                self.call_runtime("turn/interrupt", {"threadId": thread_id, "turnId": turn_id}),
                timeout=remaining_seconds(deadline)
            )
            while True:
                event = await queue.get(timeout=remaining_seconds(deadline))
                params = event.get("params", {})
                completed: dict = get_safe_dict(params, "turn")

                if event.get("method") != "turn/completed":
                    continue

                event_turn_id: str | None = params.get("turnId") or completed.get("id")

                if event_turn_id != turn_id:
                    continue

                turn: dict | None = params.get("turn")
                status: str | None = turn.get("status") if isinstance(turn, dict) else params.get("status")

                if status == "interrupted":
                    return

                raise _runtime_error(
                    ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE,
                    "Codex interrupt did not complete as interrupted",
                )

        except Exception as exc:
            await self._terminate_runtime()
            if isinstance(exc, ProviderRuntimeError):
                raise exc
            raise _timeout_error("Codex interrupt timed out", phase="interrupt") from exc

    async def _interrupt_turn_best_effort(self, thread_id: str, turn_id: str, queue: BoundedRuntimeQueue) -> None:
        try:
            await self._interrupt_turn(thread_id, turn_id, queue)
        except Exception:
            pass

    async def _start_isolated_thread(self, req: GenerateRequest, deadline: float) -> tuple[str, bool]:
        thread_params:dict = {
            "cwd": str(_RUNTIME_ROOT / "scratch"), 
            "sandbox": "read-only", 
            "approvalPolicy": "never",
            "ephemeral": True, 
            "allowProviderModelFallback": False, 
            "baseInstructions": req.system, 
            "model": req.model,
        }

        thread_start = await self.rpc(
            "thread/start", 
            thread_params, 
            timeout=remaining_seconds(deadline), 
            phase="first_delta"
        )
        thread: dict = get_safe_dict(thread_start, "thread")
        thread_id: str | None = thread.get("id") if isinstance(thread.get("id"), str) else None
        ephemeral = thread.get("ephemeral")

        if not thread_id:
            raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "codex thread/start returned no thread ID")

        if not isinstance(ephemeral, bool):
            self._schedule_thread_cleanup(thread_id, True)
            raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "codex thread/start returned no ephemeral state")

        persisted:bool = not ephemeral

        if not is_secure_thread(thread_start, req.model, _RUNTIME_ROOT / "scratch"):
            self._schedule_thread_cleanup(thread_id, persisted)
            raise _runtime_error(ProviderErrorCode.PROVIDER_CONTRACT_VIOLATION, "Codex did not apply the required isolated runtime policy")
        
        return thread_id, persisted

    async def _start_turn(self, thread_id: str, persisted: bool, req: GenerateRequest, deadline: float) -> str:
        prompt:str = "\n\n".join(f"{message.role}: {message.content}" for message in req.messages)
        try:
            turn_start = await self.rpc(
                "turn/start", 
                {
                    "threadId": thread_id, 
                    "input": [{"type": "text", "text": prompt}]
                }, 
                timeout=remaining_seconds(deadline), 
                phase="first_delta"
            )
        except Exception:
            self._schedule_thread_cleanup(thread_id, persisted)
            raise
        
        turn_id = parse_started_turn_id(turn_start)
        
        if turn_id is None:
            self._schedule_thread_cleanup(thread_id, persisted)
            raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "codex turn/start returned no turn ID")
        
        return turn_id

    def bind_auth_callbacks(
        self,
        on_login_completed: Callable[[bool], None],
        on_crash: Callable[[ProviderErrorCode | str], None]
    ) -> None:
        self._on_login_completed = on_login_completed
        self._on_crash = on_crash

    async def terminate(self) -> None:
        await self._terminate_runtime()

    @property
    def has_active_turns(self) -> bool:
        return self._generation_gate.has_active

    async def version(self) -> str:
        return await self._preflight()

    async def ensure_started(self, phase: str = "first_delta") -> None:
        async def cleanup_persisted_threads() -> None:
            try:
                cursor: str | None = None
                while True:
                    params: dict = {"cursor": cursor} if cursor else {}

                    result = await self._try_cleanup_request(
                        "thread/list",
                        params,
                        warning="Codex startup thread cleanup failed",
                    )

                    if result is None:
                        return

                    threads = result.get("data") or result.get("threads") or []

                    for thread in threads:
                        if (
                            not isinstance(thread, dict)
                            or not thread.get("id")
                            or thread.get("ephemeral")
                        ):
                            continue

                        await self._try_cleanup_request(
                            "thread/delete",
                            {"threadId": thread["id"]},
                            warning="Codex persisted thread cleanup failed",
                        )

                    cursor = result.get("nextCursor")

                    if not isinstance(cursor, str) or not cursor:
                        return
            except Exception:
                log.warning("Codex startup thread cleanup failed")

        async with self._start_lock:
            if (
                self._process
                and self._process.returncode is None
                and self._crash_error is None
            ):
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
                    _COMMAND, "app-server", "--stdio",
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(_RUNTIME_ROOT / "scratch"),
                    env=_build_runtime_env(),
                    start_new_session=True,
                    umask=RUNTIME_UMASK,
                )
            except FileNotFoundError as exc:
                raise _runtime_error(
                    ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE,
                    "codex runtime is not installed"
                ) from exc

            process = self._process
            self._current_epoch = self._connection.bind(process, self._on_notification, self._abort_connection)
            self._stderr_task = asyncio.create_task(drain_stderr(process.stderr, "codex"))

            try:
                await self.rpc(
                    "initialize",
                    {   "clientInfo": {"name": "pinballchat", "version": "0.1.0"},
                        "capabilities": {"experimentalApi": False}
                    },
                    timeout=RUNTIME_FIRST_DELTA_TIMEOUT,
                    phase=phase,
                )

                await cleanup_persisted_threads()
            except (Exception, asyncio.CancelledError):
                await self._terminate_runtime()
                raise

    async def call_runtime(self, method: str, params: dict) -> dict:
        if not self._connection.is_bound:
            raise self._crash_error or _runtime_error(
                ProviderErrorCode.PROVIDER_RUNTIME_CRASHED,
                "codex runtime is not running",
                retryable=True
            )
        try:
            return await self._connection.call(method, params)
        except ProviderRuntimeError as exc:
            # is_bound 체크 이후 crash가 끼어들 수 있으므로 최초 crash error를 우선한다.
            raise self._crash_error or exc

    async def rpc(
        self,
        method: str,
        params: dict,
        *,
        timeout: float,
        phase: str,
    ) -> dict:
        try:
            return await asyncio.wait_for(
                self.call_runtime(method, params),
                timeout=timeout
            )
        except TimeoutError as exc:
            await self._terminate_runtime()
            raise _timeout_error(f"Codex {method} timed out", phase=phase) from exc

    async def list_models(self) -> list[str]:
        await self.ensure_started()
        models: list[str] = []
        cursor: str | None = None

        while True:
            result = await self.rpc(
                "model/list",
                {"cursor": cursor} if cursor else {},
                timeout=RUNTIME_FIRST_DELTA_TIMEOUT,
                phase="first_delta"
            )

            models.extend(parse_model_page(result))

            cursor = result.get("nextCursor")

            if not cursor:
                return list(dict.fromkeys(models))

    async def shutdown(self) -> None:
        if self._cleanup_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        *tuple(self._cleanup_tasks), 
                        return_exceptions=True
                    ), 
                    timeout=RUNTIME_INTERRUPT_GRACE_SECONDS
                )
            except TimeoutError:
                for task in tuple(self._cleanup_tasks):
                    task.cancel()

        await self._terminate_runtime()

        stderr_task = self._stderr_task
        
        if stderr_task and not stderr_task.done():
            stderr_task.cancel()
        
        await self._connection.close()
        
        if stderr_task:
            await asyncio.gather(stderr_task, return_exceptions=True)
        
        self._stderr_task = None

    async def stream(self, req: GenerateRequest) -> AsyncIterator[str]:
        async def ensure_session_ready() -> None:
                try:
                    await asyncio.wait_for(self.ensure_started(), timeout=remaining_seconds(first_delta_deadline))
                except TimeoutError as exc:
                    await self._terminate_runtime()
                    raise _timeout_error("Codex runtime startup timed out", phase="first_delta") from exc

                account_result = await self.rpc("account/read", {}, 
                    timeout=remaining_seconds(first_delta_deadline), 
                    phase="first_delta"
                )

                account:dict = get_safe_dict(account_result, "account")

                if account.get("type") != "chatgpt":
                    raise _runtime_error(ProviderErrorCode.PROVIDER_AUTH_REQUIRED, "ChatGPT login is required")

        async with self._generation_gate.acquire():
            first_delta_deadline = time.monotonic() + RUNTIME_FIRST_DELTA_TIMEOUT

            await ensure_session_ready()

            thread_id, persisted = await self._start_isolated_thread(req, first_delta_deadline)
            
            turn_id = await self._start_turn(thread_id, persisted, req, first_delta_deadline)
            
            queue, overflow = await self._router.attach_turn(turn_id)
            
            if overflow:
                # _crash() await 중 재시작이 끼어들 수 있으므로 현재 process를 캡처해 identity guard와 함께 넘긴다.
                process = self._process
                if process is not None:
                    await self._abort_connection(process, self._current_epoch, overflow)
                else:
                    await self._crash(overflow)
                    
            machine:CodexTurnStateMachine = CodexTurnStateMachine(turn_id)
            
            try:
                while not machine.completed:
                    if machine.has_emitted:
                        timeout = RUNTIME_IDLE_TIMEOUT
                        timeout_phase = "idle"
                    else:
                        timeout = remaining_seconds(first_delta_deadline)
                        timeout_phase = "first_delta"

                    try:
                        event = await queue.get(timeout=timeout)
                    except TimeoutError as exc:
                        await self._interrupt_turn(thread_id, turn_id, queue)
                        raise _timeout_error("Codex generation timed out", phase=timeout_phase) from exc
                    
                    except RuntimeQueueClosed:
                        raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "codex turn route closed unexpectedly")
                    
                    if text := machine.consume_event(event):
                        yield text
            
            except (GeneratorExit, asyncio.CancelledError):
                await self._interrupt_turn_best_effort(thread_id, turn_id, queue)
                raise
            
            except ProviderRuntimeError:
                if machine.terminal_received:
                    raise

                if self._crash_error is not None:
                    raise

                await self._interrupt_turn_best_effort(thread_id, turn_id, queue)
                raise

            finally:
                self._router.mark_consumer_finished(turn_id)
                self._schedule_thread_cleanup(thread_id, persisted)
                
            if not machine.has_emitted:
                raise EmptyOutputError("codex produced no content")


runtime = CodexAppServer()

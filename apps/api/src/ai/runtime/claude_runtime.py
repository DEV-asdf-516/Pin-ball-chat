import asyncio
import json
import logging
import time
from pathlib import Path
from typing import AsyncIterator, Callable

from ai.errors import EmptyOutputError, ProviderErrorCode, ProviderRuntimeError, ProviderTimeoutError, runtime_error_factory, timeout_error_factory
from ai.protocol.claude_protocol import ClaudeTurnPhase, ClaudeTurnStateMachine, find_structure_violation
from ai.runtime.queue import BoundedRuntimeQueue, RuntimeQueueBlockedError, RuntimeQueueClosed
from ai.runtime.util import RUNTIME_UMASK, AsyncOnce, GenerationGate, ProcessOutput, drain_stderr, reap_process_group, run_subprocess_capture, runtime_env
from ai.settings import CLAUDE_COMMAND, CLAUDE_MAX_IN_FLIGHT, CLAUDE_MODELS, CLAUDE_RUNTIME_VERSION, PINBALLCHAT_RUNTIME_ROOT, RUNTIME_FIRST_DELTA_TIMEOUT, RUNTIME_IDLE_TIMEOUT, RUNTIME_INTERRUPT_GRACE_SECONDS, RUNTIME_QUEUE_BLOCK_SECONDS, RUNTIME_QUEUE_SIZE
from ai.specs import GenerateRequest, ProviderName


_COMMAND = CLAUDE_COMMAND
_VERSION = CLAUDE_RUNTIME_VERSION
_MODELS = CLAUDE_MODELS
_RUNTIME_ROOT = Path(PINBALLCHAT_RUNTIME_ROOT)

log = logging.getLogger(__name__)

_runtime_error : Callable[..., ProviderRuntimeError] = runtime_error_factory(ProviderName.CLAUDE_CLI)
_timeout_error: Callable[..., ProviderTimeoutError] = timeout_error_factory(ProviderName.CLAUDE_CLI)


def _build_runtime_env() -> dict[str, str]:
    env: dict[str, str] = runtime_env("claude-home")
    env["CLAUDE_CONFIG_DIR"] = env["HOME"]
    env["DISABLE_AUTOUPDATER"] = "1"
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    return env


class ClaudeCliRuntime:
    def __init__(self):
        self._generation_gate: GenerationGate = GenerationGate(CLAUDE_MAX_IN_FLIGHT)
        self._compatibility_cache: AsyncOnce[str] = AsyncOnce()

    @property
    def has_active_generations(self) -> bool:
        return self._generation_gate.has_active

    def auth_change_guard(self):
        # auth 변경 중 새 generation 차단 (check-then-act TOCTOU 방지).
        return self._generation_gate.try_exclusive()

    async def version(self, phase: str = "first_delta") -> str:
        try:
            output = await run_subprocess_capture(
                _COMMAND, "--version", 
                env=_build_runtime_env(), 
                timeout=RUNTIME_FIRST_DELTA_TIMEOUT, 
                grace_seconds=RUNTIME_INTERRUPT_GRACE_SECONDS
            )
        except FileNotFoundError as exc:
            raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "claude runtime is not installed") from exc
        except TimeoutError as exc:
            raise _timeout_error("Claude runtime preflight timed out", phase=phase) from exc

        version: str = output.stdout.decode(errors="replace").strip()

        if output.returncode or version not in {_VERSION, f"{_VERSION} (Claude Code)"}:
            raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "claude runtime version is incompatible")

        return version

    async def verify_compatibility(self, phase: str = "first_delta") -> str:
        async def _load_help(*args: str) -> str:
            try:
                output: ProcessOutput = await run_subprocess_capture(_COMMAND, *args, env=_build_runtime_env(), timeout=RUNTIME_FIRST_DELTA_TIMEOUT, grace_seconds=RUNTIME_INTERRUPT_GRACE_SECONDS)
            except FileNotFoundError as exc:
                raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "claude runtime is not installed") from exc
            except TimeoutError as exc:
                raise _timeout_error("Claude runtime flag check timed out", phase=phase) from exc

            if output.returncode:
                raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "claude runtime help command failed")

            return output.stdout.decode(errors="replace")

        async def _verify() -> str:
            version:str = await self.version(phase)

            help_text:str  = await _load_help("--help")

            required:str  = (
                "--print",
                "--output-format",
                "--verbose",
                "--include-partial-messages",
                "--safe-mode",
                "--system-prompt",
                "--tools",
                "--disallowedTools",
                "--strict-mcp-config",
                "--disable-slash-commands",
                "--no-chrome",
                "--no-session-persistence",
                "--model",
            )

            if any(flag not in help_text for flag in required):
                raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "claude runtime does not support the required safe streaming flags")

            auth_help:str = await _load_help("auth", "--help")

            if any(command not in auth_help for command in ("login", "logout", "status")):
                raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "claude runtime does not support the required authentication commands")

            login_help:str = await _load_help("auth", "login", "--help")

            status_help:str = await _load_help("auth", "status", "--help")

            if "--claudeai" not in login_help or "--json" not in status_help:
                raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "claude runtime does not support the required authentication flags")

            return version

        return await self._compatibility_cache.get(_verify)

    async def _read_event_stream(self, stream: asyncio.StreamReader, queue: BoundedRuntimeQueue) -> None:
        try:
            while line := await stream.readline():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    await queue.fail(_runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "claude runtime emitted malformed JSON"))
                    return

                if not isinstance(event, dict):
                    await queue.fail(_runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "claude runtime emitted a malformed stream event"))
                    return

                structure_violation = find_structure_violation(event)

                if structure_violation:
                    await queue.fail(_runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, structure_violation))
                    return

                try:
                    await queue.put(event)
                except RuntimeQueueBlockedError:
                    await queue.fail(_timeout_error("Claude event queue was blocked", phase="idle"))
                    return
                except RuntimeQueueClosed:
                    # consumer가 이미 실패/취소를 관찰했으므로 조용히 종료.
                    return
        finally:
            try:
                await queue.close()
            except asyncio.CancelledError:
                pass

    async def _spawn_generation_process(self, req: GenerateRequest, scratch: Path, remaining: Callable[[], float]) -> asyncio.subprocess.Process:
        command = [
            _COMMAND,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--safe-mode",
            "--system-prompt",
            req.system,
            "--tools",
            "",
            "--disallowedTools",
            "mcp__*",
            "--strict-mcp-config",
            "--disable-slash-commands",
             "--no-chrome",
             "--no-session-persistence",
        ]
        if req.model:
            command.extend(["--model", req.model])
        try:
            return await asyncio.wait_for(
                asyncio.create_subprocess_exec(*command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=str(scratch), env=_build_runtime_env(), start_new_session=True, umask=RUNTIME_UMASK),
                timeout=remaining(),
            )
        except FileNotFoundError as exc:
            raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "claude runtime is not installed") from exc
        except TimeoutError as exc:
            raise _timeout_error("Claude runtime spawn timed out", phase="first_delta") from exc

    async def _write_prompt(self, process: asyncio.subprocess.Process, req: GenerateRequest, remaining: Callable[[], float]) -> None:
        assert process.stdin and process.stdout

        prompt = "\n\n".join(f"{message.role}: {message.content}" for message in req.messages)

        process.stdin.write(prompt.encode())

        try:
            await asyncio.wait_for(process.stdin.drain(), timeout=remaining())
        except TimeoutError as exc:
            raise _timeout_error("Claude prompt delivery timed out", phase="first_delta") from exc

        process.stdin.close()

    async def _validate_generation_completion(self, process: asyncio.subprocess.Process, stdout_task: asyncio.Task | None, machine: ClaudeTurnStateMachine, model: str) -> None:

        if stdout_task:
            await stdout_task
        try:
            exit_code = await asyncio.wait_for(process.wait(), timeout=RUNTIME_INTERRUPT_GRACE_SECONDS)
        except TimeoutError as exc:
            await reap_process_group(process, RUNTIME_INTERRUPT_GRACE_SECONDS)
            raise _timeout_error("Claude runtime exit timed out", phase="interrupt") from exc
        
        result_seen: bool = machine.phase in (ClaudeTurnPhase.FINISHED, ClaudeTurnPhase.FINISHED_WITHOUT_INIT)
        init_seen: bool= machine.phase in (ClaudeTurnPhase.STREAMING, ClaudeTurnPhase.FINISHED)

        if exit_code:
            if not result_seen:
                raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_CRASHED, "claude runtime exited unexpectedly", retryable=True)
            raise _runtime_error(ProviderErrorCode.PROVIDER_BAD_GATEWAY, "claude runtime exited with an error", retryable=True)
        
        if not init_seen:
            raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "claude runtime ended without initialization")
        
        if not result_seen:
            raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "claude runtime ended without a result event")
        
        if machine.result_text != "".join(machine.emitted_text):
            raise _runtime_error(ProviderErrorCode.PROVIDER_CONTRACT_VIOLATION, "Claude result did not match the streamed text")
        
        if not machine.has_emitted_text:
            raise EmptyOutputError("claude produced no content")
        
        log.info(
            "Claude usage: model=%s input_tokens=%s cache_creation_input_tokens=%s cache_read_input_tokens=%s output_tokens=%s",
            model,
            machine.result_usage.get("input_tokens"),
            machine.result_usage.get("cache_creation_input_tokens"),
            machine.result_usage.get("cache_read_input_tokens"),
            machine.result_usage.get("output_tokens"),
        )

    async def stream(self, req: GenerateRequest) -> AsyncIterator[str]:
        if req.model not in _MODELS:
            raise _runtime_error(ProviderErrorCode.MODEL_UNAVAILABLE, "the selected Claude model is unavailable")

        async with self._generation_gate.acquire():
            scratch = _RUNTIME_ROOT / "scratch"
            first_delta_deadline = time.monotonic() + RUNTIME_FIRST_DELTA_TIMEOUT

            def first_delta_remaining() -> float:
                return max(0.001, first_delta_deadline - time.monotonic())

            process: asyncio.subprocess.Process | None = None
            stdout_task: asyncio.Task | None = None
            stderr_task: asyncio.Task | None = None
            queue: BoundedRuntimeQueue = BoundedRuntimeQueue(maxsize=RUNTIME_QUEUE_SIZE, block_seconds=RUNTIME_QUEUE_BLOCK_SECONDS)

            try:
                try:
                    await asyncio.wait_for(self.verify_compatibility(), timeout=first_delta_remaining())
                except TimeoutError as exc:
                    raise _timeout_error("Claude runtime startup timed out", phase="first_delta") from exc

                process = await self._spawn_generation_process(req, scratch, first_delta_remaining)

                await self._write_prompt(process, req, first_delta_remaining)

                stdout_task = asyncio.create_task(self._read_event_stream(process.stdout, queue))
                stderr_task = asyncio.create_task(drain_stderr(process.stderr, "claude"))
                machine: ClaudeTurnStateMachine = ClaudeTurnStateMachine(scratch)

                while True:
                    timeout = RUNTIME_IDLE_TIMEOUT if machine.has_emitted_text else first_delta_remaining()
                    try:
                        event = await queue.get(timeout=timeout)
                    except TimeoutError as exc:
                        await reap_process_group(process, RUNTIME_INTERRUPT_GRACE_SECONDS)
                        raise _timeout_error("Claude generation timed out", phase="idle" if machine.has_emitted_text else "first_delta") from exc
                    except RuntimeQueueClosed:
                        break
                    if text := machine.consume_event(event):
                        yield text
                
                await self._validate_generation_completion(process, stdout_task, machine, req.model)

            except (GeneratorExit, asyncio.CancelledError):
                if process:
                    await reap_process_group(process, RUNTIME_INTERRUPT_GRACE_SECONDS)
                raise

            finally:
                if process and process.returncode is None:
                    await reap_process_group(process, RUNTIME_INTERRUPT_GRACE_SECONDS)
                
                for task in (stdout_task, stderr_task):
                    if task and not task.done():
                        task.cancel()
                
                pending_tasks = [task for task in (stdout_task, stderr_task) if task]
                
                if pending_tasks:
                    await asyncio.gather(*pending_tasks, return_exceptions=True)


runtime = ClaudeCliRuntime()

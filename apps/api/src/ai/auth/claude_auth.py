import asyncio
import re
import time
from dataclasses import dataclass, field, replace
from typing import Callable

from ai.errors import ProviderErrorCode, ProviderRuntimeError, ProviderTimeoutError, runtime_error_factory, timeout_error_factory
from ai.specs import ProviderName
from ai.runtime.claude_runtime import _COMMAND, _RUNTIME_ROOT, _build_runtime_env, runtime, ClaudeCliRuntime
from ai.runtime.util import RUNTIME_UMASK, GenerationGateBusyError, reap_process_group, remaining_seconds, run_subprocess_capture
from ai.settings import RUNTIME_FIRST_DELTA_TIMEOUT, RUNTIME_INTERRUPT_GRACE_SECONDS, RUNTIME_LOGIN_TIMEOUT
from util.safe_util import parse_json_dict


_url_pattern = re.compile(r"https?://[^\s\]\)]+")
_runtime_error: Callable[..., ProviderRuntimeError] = runtime_error_factory(ProviderName.CLAUDE_CLI)
_timeout_error: Callable[..., ProviderTimeoutError] = timeout_error_factory(ProviderName.CLAUDE_CLI)


async def _wait_with_login_deadline(awaitable, deadline: float):
    try:
        return await asyncio.wait_for(
            awaitable,
            timeout=remaining_seconds(deadline)
        )
    except TimeoutError as exc:
        raise _timeout_error("Claude login timed out", phase="login") from exc


async def _run_auth_command(*args: str, timeout: float = RUNTIME_FIRST_DELTA_TIMEOUT) -> tuple[int, str]:
    try:
        output = await run_subprocess_capture(
            _COMMAND,
            *args,
             env=_build_runtime_env(),
             timeout=timeout,
             grace_seconds=RUNTIME_INTERRUPT_GRACE_SECONDS,
             cwd=str(_RUNTIME_ROOT / "scratch")
            )
    except FileNotFoundError as exc:
        raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "claude runtime is not installed") from exc
    except TimeoutError as exc:
        raise _timeout_error("Claude authentication command timed out", phase="login") from exc

    return output.returncode, output.stdout.decode(errors="replace")


class ClaudeGenerationActiveError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class _ClaudeLoginState:
    status: str
    verification_url: str | None = None
    user_code: str | None = None
    account_label: str | None = None
    plan: str | None = None
    error_code: ProviderErrorCode | str | None = None
    phase: str | None = None
    started_at: float | None = None

    def to_payload(self) -> dict:
        result: dict = {
            "status": self.status,
            "verificationUrl": self.verification_url,
            "userCode": self.user_code,
            "accountLabel": self.account_label,
            "errorCode": self.error_code,
        }
        optional: dict = {
            "plan": self.plan,
            "phase": self.phase,
            "startedAt": self.started_at,
        }
        result.update({key: value for key, value in optional.items() if value is not None})
        return result


@dataclass(slots=True)
class _LoginAttempt:
    # 진행 중엔 attempt.state만 바뀐다. session._state 반영은 _finish_attempt()가 한 번만.
    process: asyncio.subprocess.Process
    started_at: float
    deadline: float
    state: _ClaudeLoginState = field(default_factory=lambda: _ClaudeLoginState(status="login_pending"))
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    outcome: _ClaudeLoginState | None = None
    watcher: "asyncio.Task[None] | None" = None


@dataclass(frozen=True, slots=True)
class _CliAuthStatus:
    connected: bool
    account_label: str | None
    plan: str | None

    @classmethod
    async def query(cls) -> "_CliAuthStatus":
        try:
            code, output = await _run_auth_command("auth", "status", "--json")
            data: dict | None = parse_json_dict(output) if code == 0 else None
        except (OSError, ProviderRuntimeError):
            data = None
        data = data or {}
        return cls(
            connected=bool(data.get("loggedIn") or data.get("authenticated") or data.get("isAuthenticated")),
            account_label=data.get("email") or data.get("accountEmail"),
            plan=data.get("subscriptionType") or data.get("plan"),
        )

class _ClaudeAuthSession:
    def __init__(self, runtime: ClaudeCliRuntime):
        self._runtime = runtime
        self._lock = asyncio.Lock()
        self._state = _ClaudeLoginState(status="disconnected")
        self._attempt: _LoginAttempt | None = None

    def _has_running_attempt(self) -> bool:
        return bool(self._attempt and self._attempt.process.returncode is None)

    @property
    def _current_state(self) -> _ClaudeLoginState:
        if self._attempt is not None:
            return self._attempt.state
        return self._state

    def _finish_attempt(self, attempt: _LoginAttempt) -> None:
        if self._attempt is not attempt:
            return
        self._state = attempt.state
        self._attempt = None

    async def _refresh_login_state(self) -> tuple[_ClaudeLoginState, _CliAuthStatus]:
        auth = await _CliAuthStatus.query()

        if auth.connected:
            self._state = _ClaudeLoginState(
                status="connected", 
                account_label=auth.account_label, 
                plan=auth.plan
            )
            return self._state, auth

        if (
            not self._has_running_attempt()
            and self._state.status in {"connected", "login_pending"}
        ):
            self._state = _ClaudeLoginState(
                status="disconnected", 
                error_code=ProviderErrorCode.LOGIN_REQUIRED
            )

        return self._state, auth

    async def status(self) -> dict:
        # lock을 잡으면 login() -> status() 데드락.
        _, auth = await self._refresh_login_state()
        result: dict = self._current_state.to_payload()

        optional: dict = {
            "accountLabel": auth.account_label,
            "plan": auth.plan,
        }

        result.update({key: value for key, value in optional.items() if value})

        return result

    async def _monitor_login_attempt(self, attempt: _LoginAttempt) -> None:
        async def _read_login_output() -> None:
            stream: asyncio.StreamReader | None = attempt.process.stdout

            if not stream:
                return

            while line := await stream.readline():
                text: str = line.decode(errors="replace")
                match: re.Match[str] | None = _url_pattern.search(text)

                if not match:
                    continue

                verification_url: str = match.group(0)
                attempt.state = replace(attempt.state, verification_url=verification_url)

                if attempt.outcome is None:
                    attempt.outcome = _ClaudeLoginState(
                        status="login_pending",
                        verification_url=verification_url,
                        started_at=attempt.started_at
                    )

                attempt.ready.set()

        stdout_task = asyncio.create_task(_read_login_output())

        try:
            await asyncio.wait_for(
                attempt.process.wait(),
                timeout=remaining_seconds(attempt.deadline)
            )

            auth = await _CliAuthStatus.query()

            if auth.connected:
                attempt.state = _ClaudeLoginState(
                    status="connected", 
                    account_label=auth.account_label, 
                    plan=auth.plan
                )
            else:
                error_code:ProviderErrorCode = ProviderErrorCode.PROVIDER_AUTH_REQUIRED \
                    if attempt.state.verification_url \
                    else ProviderErrorCode.PROVIDER_RUNTIME_CRASHED
                
                attempt.state = replace(
                    attempt.state, 
                    status="error", 
                    error_code=error_code
                )

        except TimeoutError:
            await reap_process_group(attempt.process, RUNTIME_INTERRUPT_GRACE_SECONDS)
            attempt.state = replace(
                attempt.state,
                status="error",
                error_code=ProviderErrorCode.PROVIDER_TIMEOUT,
                phase="login"
            )

        except (ProviderTimeoutError, ProviderRuntimeError):
            # fire-and-forget task라 안 잡으면 예외가 유실된다.
            attempt.state = replace(
                attempt.state, 
                status="error", 
                error_code=ProviderErrorCode.PROVIDER_RUNTIME_CRASHED
            )

        finally:
            if not stdout_task.done():
                stdout_task.cancel()
            
            await asyncio.gather(stdout_task, return_exceptions=True)

            if attempt.outcome is None:
                attempt.outcome = attempt.state

            attempt.ready.set()
            self._finish_attempt(attempt)

    async def _wait_for_verification_url(self, attempt: _LoginAttempt, deadline: float) -> dict:
        try:
            await _wait_with_login_deadline(attempt.ready.wait(), deadline)
        except ProviderTimeoutError:
            # self._attempt를 다시 조회하면 새로 시작된 다른 attempt를 죽일 수 있다.
            if attempt.process.returncode is None:
                await reap_process_group(attempt.process, RUNTIME_INTERRUPT_GRACE_SECONDS)
        
            attempt.state = replace(
                attempt.state, 
                status="error", 
                error_code=ProviderErrorCode.PROVIDER_TIMEOUT, 
                phase="login"
            )
            self._finish_attempt(attempt)
            raise
        
        outcome:_ClaudeLoginState = attempt.outcome or _ClaudeLoginState(status="error", error_code=ProviderErrorCode.PROVIDER_RUNTIME_CRASHED)
        
        if outcome.verification_url:
            return outcome.to_payload()

        error_code:ProviderErrorCode|str = outcome.error_code or ProviderErrorCode.PROVIDER_RUNTIME_CRASHED
        
        if error_code == ProviderErrorCode.PROVIDER_TIMEOUT:
            raise _timeout_error("Claude login timed out", phase="login")
        
        raise _runtime_error(error_code, "Claude login did not provide an authorization URL", retryable=error_code == ProviderErrorCode.PROVIDER_RUNTIME_CRASHED)

    async def login(self) -> dict:
        started_at:float = time.monotonic()
        deadline:float = started_at + RUNTIME_LOGIN_TIMEOUT

        async with self._lock:
            state, _ = await self._refresh_login_state()

            if state.status == "connected":
                return state.to_payload()

            if self._has_running_attempt():
                assert self._attempt is not None
                attempt = self._attempt

                if attempt.state.verification_url:
                    return attempt.state.to_payload()
            else:
                await _wait_with_login_deadline(self._runtime.verify_compatibility("login"), deadline)

                process = await _wait_with_login_deadline(
                    asyncio.create_subprocess_exec(
                        _COMMAND, "auth", "login", "--claudeai",
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                        cwd=str(_RUNTIME_ROOT / "scratch"),
                        env=_build_runtime_env(),
                        start_new_session=True,
                        umask=RUNTIME_UMASK,
                    ),
                    deadline,
                )
                assert process.stdout is not None

                attempt = _LoginAttempt(
                    process=process,
                    started_at=started_at,
                    deadline=deadline,
                    state=_ClaudeLoginState(status="login_pending", started_at=started_at),
                )
                self._attempt = attempt
                attempt.watcher = asyncio.create_task(self._monitor_login_attempt(attempt))

        return await self._wait_for_verification_url(attempt, deadline)

    async def submit_login_code(self, code: str) -> dict:
        async with self._lock:
            
            stripped_code:str = code.strip()

            if not stripped_code or any(char in stripped_code for char in "\r\n"):
                raise _runtime_error(
                    ProviderErrorCode.PROVIDER_AUTH_REQUIRED, 
                    "Invalid Claude authorization code"
                )

            attempt = self._attempt

            if (
                attempt is None
                or attempt.process.returncode is not None
                or attempt.process.stdin is None
            ):
                raise _runtime_error(
                    ProviderErrorCode.PROVIDER_AUTH_REQUIRED, 
                    "Claude login is not waiting for an authorization code"
                )

            try:
                attempt.process.stdin.write((stripped_code + "\n").encode())
                await asyncio.wait_for(attempt.process.stdin.drain(), timeout=RUNTIME_INTERRUPT_GRACE_SECONDS)
            
            except TimeoutError as exc:
                await reap_process_group(attempt.process, RUNTIME_INTERRUPT_GRACE_SECONDS)
                raise _timeout_error("Claude authorization code submission timed out", phase="login") from exc
            
            except (BrokenPipeError, ConnectionResetError) as exc:
                raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_CRASHED, "Claude login process exited unexpectedly", retryable=True) from exc
            
            return {"status": self._current_state.status}

    async def logout(self) -> None:
        async with self._lock:
            # auth_change_guard() 진입 성공 = generation 없음이 보장됨.
            try:
                async with self._runtime.auth_change_guard():
                    await self._stop_login_attempt()

                    code, _ = await _run_auth_command("auth", "logout")

                    if code:
                        raise _runtime_error(ProviderErrorCode.PROVIDER_BAD_GATEWAY, "Claude logout failed", retryable=True)

            except GenerationGateBusyError as exc:
                raise ClaudeGenerationActiveError("cannot log out while a Claude generation is running") from exc

            self._attempt = None
            self._state = _ClaudeLoginState(status="disconnected")

    async def _stop_login_attempt(self) -> None:
        attempt = self._attempt

        if attempt and attempt.process.returncode is None:
            await reap_process_group(attempt.process, RUNTIME_INTERRUPT_GRACE_SECONDS)

        watcher:asyncio.Task = attempt.watcher if attempt else None

        if watcher and not watcher.done():
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)

    async def shutdown(self) -> None:
        await self._stop_login_attempt()
        self._attempt = None


session = _ClaudeAuthSession(runtime)

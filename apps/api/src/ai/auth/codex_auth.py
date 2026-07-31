import asyncio
import time
from dataclasses import dataclass
from typing import Callable

from ai.errors import ProviderErrorCode, ProviderRuntimeError, ProviderTimeoutError, runtime_error_factory, timeout_error_factory
from ai.protocol.codex_protocol import is_valid_device_login
from ai.runtime.codex.runtime import CodexAppServer, runtime as codex_runtime
from ai.runtime.util import remaining_seconds
from ai.settings import RUNTIME_INTERRUPT_GRACE_SECONDS, RUNTIME_LOGIN_TIMEOUT
from ai.specs import ProviderName
from util.safe_util import get_safe_dict


_runtime_error: Callable[..., ProviderRuntimeError] = runtime_error_factory(ProviderName.OPENAI_CODEX)
_timeout_error: Callable[..., ProviderTimeoutError] = timeout_error_factory(ProviderName.OPENAI_CODEX)


@dataclass(frozen=True, slots=True)
class _CodexLoginState:
    status: str
    verification_url: str | None = None
    user_code: str | None = None
    error_code: ProviderErrorCode | str | None = None
    phase: str | None = None
    started_at: float | None = None
    login_id: str | None = None

    def to_payload(self) -> dict:
        result: dict = {
            "status": self.status,
            "verificationUrl": self.verification_url,
            "userCode": self.user_code,
            "errorCode": self.error_code,
        }
        optional: dict = {
            "phase": self.phase,
            "startedAt": self.started_at,
            "loginId": self.login_id,
        }
        result.update({key: value for key, value in optional.items() if value is not None})
        return result


class CodexAuthSession:
    def __init__(self, runtime: CodexAppServer):
        self._runtime = runtime
        self._login_lock = asyncio.Lock()
        self._login_timeout_task: asyncio.Task | None = None
        self._login_state = _CodexLoginState(status="disconnected")
        runtime.bind_auth_callbacks(self._on_login_completed, self._on_crash)

    def _on_login_completed(self, success: bool) -> None:
        if success:
            self._login_state = _CodexLoginState(status="connected")
        else:
            self._login_state = _CodexLoginState(status="error", error_code=ProviderErrorCode.PROVIDER_AUTH_REQUIRED)
        
        if self._login_timeout_task and not self._login_timeout_task.done():
            self._login_timeout_task.cancel()

    def _on_crash(self, code: ProviderErrorCode | str) -> None:
        if self._login_state.status == "login_pending":
            self._login_state = _CodexLoginState(status="error", error_code=code)

    async def read_account(self) -> dict:
        await self._runtime.ensure_started("login")
        result = await self._runtime.rpc("account/read", {}, timeout=RUNTIME_LOGIN_TIMEOUT, phase="login")
        account:dict = get_safe_dict(result, "account")
        
        if account.get("type") == "chatgpt":
            self._login_state = _CodexLoginState(status="connected")

        elif self._login_state.status == "connected":
            self._login_state = _CodexLoginState(status="disconnected")
        
        return result

    async def start_login(self) -> dict:
        async with self._login_lock:
            if self.get_login_state()["status"] == "login_pending":
                return self.get_login_state()
            started_at = time.monotonic()
            deadline = started_at + RUNTIME_LOGIN_TIMEOUT

            def remaining() -> float:
                return remaining_seconds(deadline)

            try:
                await asyncio.wait_for(self._runtime.ensure_started("login"), timeout=remaining())
            except TimeoutError as exc:
                await self._runtime.terminate()
                raise _timeout_error("Codex login timed out", phase="login") from exc

            self._login_state = _CodexLoginState(status="disconnected")

            result = await self._runtime.rpc("account/login/start", {"type": "chatgptDeviceCode"}, timeout=remaining(), phase="login")

            if not is_valid_device_login(result):
                raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "codex runtime returned a malformed device login response")

            if self._login_state.status in {"connected", "error"}:
                return self._login_state.to_payload()

            self._login_state = _CodexLoginState(
                status="login_pending",
                verification_url=result.get("verificationUrl"),
                user_code=result.get("userCode"),
                started_at=started_at,
                login_id=result.get("loginId"),
            )

            self._login_timeout_task = asyncio.create_task(self._expire_login_at_deadline(result.get("loginId"), deadline))

            return result

    async def _expire_login_at_deadline(self, login_id: str | None, deadline: float) -> None:
        await asyncio.sleep(remaining_seconds(deadline))

        if self._login_state.status != "login_pending":
            return

        if login_id:
            try:
                await asyncio.wait_for(
                    self._runtime.call_runtime(
                        "account/login/cancel",
                        {"loginId": login_id}
                    ),
                    timeout=RUNTIME_INTERRUPT_GRACE_SECONDS
                )
            except Exception:
                await self._runtime.terminate()

        self._login_state = _CodexLoginState(
            status="error", 
            error_code=ProviderErrorCode.PROVIDER_TIMEOUT, 
            phase="login"
        )

    def get_login_state(self) -> dict:
        login_timed_out = (
            self._login_state.status == "login_pending"
            and self._login_state.started_at is not None
            and time.monotonic() - self._login_state.started_at > RUNTIME_LOGIN_TIMEOUT
        )
        if login_timed_out:
            self._login_state = _CodexLoginState(
                status="error", 
                error_code=ProviderErrorCode.PROVIDER_TIMEOUT,
                phase="login"
            )
        
        return self._login_state.to_payload()

    async def logout(self) -> None:
        async with self._login_lock:
            if self._runtime.has_active_turns:
                raise _runtime_error(
                    ProviderErrorCode.PROVIDER_BAD_GATEWAY, 
                    "cannot log out while a Codex generation is running"
                )

            await self._runtime.ensure_started("login")
            
            login_id = self._login_state.login_id if self._login_state.status == "login_pending" else None

            if isinstance(login_id, str):
                try:
                    await self._runtime.rpc("account/login/cancel", {"loginId": login_id}, timeout=RUNTIME_INTERRUPT_GRACE_SECONDS, phase="interrupt")
                except ProviderRuntimeError:
                    pass

            await self._runtime.rpc(
                "account/logout",
                {},
                timeout=RUNTIME_INTERRUPT_GRACE_SECONDS,
                phase="interrupt"
            )

            if self._login_timeout_task and not self._login_timeout_task.done():
                self._login_timeout_task.cancel()

            self._login_state = _CodexLoginState(status="disconnected")

    async def shutdown(self) -> None:
        if self._login_timeout_task and not self._login_timeout_task.done():
            self._login_timeout_task.cancel()
            await asyncio.gather(self._login_timeout_task, return_exceptions=True)


session = CodexAuthSession(codex_runtime)


async def shutdown_codex() -> None:
    await codex_runtime.shutdown()   # terminate → reader 정리 (현행 그대로)
    await session.shutdown()         # login timeout task 취소 (현행 shutdown의 마지막 단계)

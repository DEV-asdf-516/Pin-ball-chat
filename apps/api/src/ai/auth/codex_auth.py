import asyncio
import time
from typing import Callable

from ai.errors import ProviderErrorCode, ProviderRuntimeError, ProviderTimeoutError, runtime_error_factory, timeout_error_factory
from ai.protocol.codex_protocol import is_valid_device_login
from ai.runtime.codex_runtime import CodexAppServer, runtime as codex_runtime
from ai.settings import RUNTIME_INTERRUPT_GRACE_SECONDS, RUNTIME_LOGIN_TIMEOUT
from ai.specs import ProviderName
from util.safe_util import get_safe_dict


_runtime_error: Callable[..., ProviderRuntimeError] = runtime_error_factory(ProviderName.OPENAI_CODEX)
_timeout_error: Callable[..., ProviderTimeoutError] = timeout_error_factory(ProviderName.OPENAI_CODEX)


class CodexAuthSession:
    def __init__(self, runtime: CodexAppServer):
        self._runtime = runtime
        self._login_lock = asyncio.Lock()
        self._login_timeout_task: asyncio.Task | None = None
        self._login_state: dict = {"status": "disconnected", "verificationUrl": None, "userCode": None, "errorCode": None}
        runtime.bind_login_hooks(self._on_login_completed, self._on_crash)

    def _on_login_completed(self, success: bool) -> None:
        if success:
            self._login_state = {"status": "connected", "verificationUrl": None, "userCode": None, "errorCode": None}
        else:
            self._login_state = {"status": "error", "verificationUrl": None, "userCode": None, "errorCode": ProviderErrorCode.PROVIDER_AUTH_REQUIRED}
        if self._login_timeout_task and not self._login_timeout_task.done():
            self._login_timeout_task.cancel()

    def _on_crash(self, code: ProviderErrorCode | str) -> None:
        if self._login_state.get("status") == "login_pending":
            self._login_state = {"status": "error", "verificationUrl": None, "userCode": None, "errorCode": code}

    async def account(self) -> dict:
        await self._runtime.ensure_started("login")
        result = await self._runtime.rpc("account/read", {}, RUNTIME_LOGIN_TIMEOUT, "login")
        account = get_safe_dict(result, "account")
        if account.get("type") == "chatgpt":
            self._login_state = {"status": "connected", "verificationUrl": None, "userCode": None, "errorCode": None}
        elif self._login_state.get("status") == "connected":
            self._login_state = {"status": "disconnected", "verificationUrl": None, "userCode": None, "errorCode": None}
        return result

    async def login(self) -> dict:
        async with self._login_lock:
            return await self._login()

    async def _login(self) -> dict:
        if self.login_state()["status"] == "login_pending":
            return self.login_state()
        started_at = time.monotonic()
        deadline = started_at + RUNTIME_LOGIN_TIMEOUT

        def remaining() -> float:
            return max(0.001, deadline - time.monotonic())

        try:
            await asyncio.wait_for(self._runtime.ensure_started("login"), timeout=remaining())
        except TimeoutError as exc:
            await self._runtime.terminate()
            raise _timeout_error("Codex login timed out", phase="login") from exc
        self._login_state = {"status": "disconnected", "verificationUrl": None, "userCode": None, "errorCode": None}
        result = await self._runtime.rpc("account/login/start", {"type": "chatgptDeviceCode"}, remaining(), "login")
        if not is_valid_device_login(result):
            raise _runtime_error(ProviderErrorCode.PROVIDER_RUNTIME_INCOMPATIBLE, "codex runtime returned a malformed device login response")
        if self._login_state.get("status") in {"connected", "error"}:
            return self._login_state
        self._login_state = {
            "status": "login_pending", "verificationUrl": result.get("verificationUrl"),
            "userCode": result.get("userCode"), "errorCode": None, "startedAt": started_at,
            "loginId": result.get("loginId"),
        }
        self._login_timeout_task = asyncio.create_task(self._expire_login(result.get("loginId"), deadline))
        return result

    async def _expire_login(self, login_id: str | None, deadline: float) -> None:
        try:
            await asyncio.sleep(max(0.001, deadline - time.monotonic()))
            if self._login_state.get("status") != "login_pending":
                return
            if login_id:
                try:
                    await asyncio.wait_for(self._runtime.raw_request("account/login/cancel", {"loginId": login_id}), timeout=RUNTIME_INTERRUPT_GRACE_SECONDS)
                except Exception:
                    await self._runtime.terminate()
            self._login_state = {"status": "error", "verificationUrl": None, "userCode": None, "errorCode": ProviderErrorCode.PROVIDER_TIMEOUT, "phase": "login"}
        except asyncio.CancelledError:
            pass

    def login_state(self) -> dict:
        if self._login_state.get("status") == "login_pending" and time.monotonic() - self._login_state.get("startedAt", 0) > RUNTIME_LOGIN_TIMEOUT:
            self._login_state = {"status": "error", "verificationUrl": None, "userCode": None, "errorCode": ProviderErrorCode.PROVIDER_TIMEOUT, "phase": "login"}
        return self._login_state

    async def logout(self) -> None:
        async with self._login_lock:
            await self._logout()

    async def _logout(self) -> None:
        if self._runtime.has_active_turns:
            raise _runtime_error(ProviderErrorCode.PROVIDER_BAD_GATEWAY, "cannot log out while a Codex generation is running")
        await self._runtime.ensure_started("login")
        login_id = self._login_state.get("loginId") if self._login_state.get("status") == "login_pending" else None
        if isinstance(login_id, str):
            try:
                await self._runtime.rpc("account/login/cancel", {"loginId": login_id}, RUNTIME_INTERRUPT_GRACE_SECONDS, "interrupt")
            except ProviderRuntimeError:
                pass
        await self._runtime.rpc("account/logout", {}, RUNTIME_INTERRUPT_GRACE_SECONDS, "interrupt")
        if self._login_timeout_task and not self._login_timeout_task.done():
            self._login_timeout_task.cancel()
        self._login_state = {"status": "disconnected", "verificationUrl": None, "userCode": None, "errorCode": None}

    async def shutdown(self) -> None:
        if self._login_timeout_task and not self._login_timeout_task.done():
            self._login_timeout_task.cancel()
            await asyncio.gather(self._login_timeout_task, return_exceptions=True)


session = CodexAuthSession(codex_runtime)


async def shutdown_codex() -> None:
    await codex_runtime.shutdown()   # terminate → reader 정리 (현행 그대로)
    await session.shutdown()         # login timeout task 취소 (현행 shutdown의 마지막 단계)

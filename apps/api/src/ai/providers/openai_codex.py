from typing import AsyncIterator

from ai.auth import codex_auth
from ai.errors import ProviderConnectionBusyError, ProviderErrorCode
from ai.providers.base import LoginCapableProvider
from ai.providers.timing import log_stream_timing
from ai.runtime.codex_runtime import runtime
from ai.specs import GenerateRequest, ProviderConnection, ProviderName


class OpenAICodexProvider(LoginCapableProvider):
    name = ProviderName.OPENAI_CODEX

    @log_stream_timing
    async def stream(self, req: GenerateRequest) -> AsyncIterator[str]:
        async for token in runtime.stream(req):
            yield token

    async def list_models(self) -> list[str]:
        return await runtime.list_models()

    async def connection(self) -> ProviderConnection:
        try:
            result = await codex_auth.session.account()
            account = result.get("account") or {}
            connected = account.get("type") == "chatgpt"
            login = codex_auth.session.login_state()
            return ProviderConnection(
                provider=self.name,
                status="connected" if connected else login["status"],
                action_required=None if connected else (login.get("errorCode") or ProviderErrorCode.LOGIN_REQUIRED),
                credential_type="subscription_oauth",
                runtime_version=await runtime.version(),
                resolved_auth_mode="chatgpt" if connected else None,
                account_label=account.get("email") if connected else None,
                plan=account.get("planType") if connected else None,
                verification_url=login.get("verificationUrl"),
                user_code=login.get("userCode"),
            )
        except Exception as exc:
            return self._connection_from_error(credential_type="subscription_oauth", exc=exc)

    async def start_login(self) -> dict:
        return await codex_auth.session.login()

    async def logout(self) -> None:
        if runtime.has_active_turns:
            raise ProviderConnectionBusyError("cannot log out while a Codex generation is running")
        await codex_auth.session.logout()

from typing import AsyncIterator

from ai.auth import claude_auth
from ai.errors import ProviderConnectionBusyError, ProviderErrorCode
from ai.runtime.claude_runtime import _MODELS, runtime
from ai.providers.base import LoginCapableProvider
from ai.providers.timing import log_stream_timing
from ai.specs import GenerateRequest, ProviderConnection, ProviderName


class ClaudeCliProvider(LoginCapableProvider):
    name = ProviderName.CLAUDE_CLI

    async def list_models(self) -> list[str]:
        await runtime.verify_compatibility()
        return list(_MODELS)

    @log_stream_timing
    async def stream(self, req: GenerateRequest) -> AsyncIterator[str]:
        async for token in runtime.stream(req):
            yield token

    async def connection(self) -> ProviderConnection:
        try:
            runtime_version = await runtime.verify_compatibility()
            auth = await claude_auth.session.status()
            connected = auth["status"] == "connected"
            return ProviderConnection(
                provider=self.name,
                status=auth["status"],
                action_required=None if connected else (auth.get("errorCode") or ProviderErrorCode.LOGIN_REQUIRED),
                credential_type="subscription_oauth",
                runtime_version=runtime_version,
                resolved_auth_mode="claude_subscription" if connected else None,
                account_label=auth.get("accountLabel"),
                plan=auth.get("plan"),
                verification_url=auth.get("verificationUrl"),
                user_code=auth.get("userCode"),
            )
        except Exception as exc:
            return self._connection_from_error(
                credential_type="subscription_oauth", exc=exc)

    async def start_login(self) -> dict:
        return await claude_auth.session.login()

    async def submit_login_code(self, code: str) -> dict:
        return await claude_auth.session.submit_login_code(code)

    async def logout(self) -> None:
        try:
            await claude_auth.session.logout()
        except claude_auth.ClaudeGenerationActiveError as exc:
            raise ProviderConnectionBusyError(str(exc)) from exc

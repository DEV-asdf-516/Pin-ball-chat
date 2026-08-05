from abc import ABC, abstractmethod
from typing import AsyncIterator

from ai.auth.api_key_store import stored_key_source
from ai.errors import ProviderErrorCode, provider_failure_code
from ai.specs import GenerateRequest, ProviderConnection, ProviderName
from util.singleton import Singleton


class AIProvider(Singleton, ABC):
    name: ProviderName

    @abstractmethod
    def stream(self, req: GenerateRequest) -> AsyncIterator[str]: ...

    async def list_models(self) -> list[str]:
        raise NotImplementedError(f"{self.name} does not support listing models")

    async def connection(self) -> ProviderConnection:
        raise NotImplementedError(f"{self.name} does not support connection status")

    def _api_key_connection(self, credential_type: str, auth_mode: str, env_name: str) -> ProviderConnection:
        key_source = stored_key_source(env_name)
        connected = key_source is not None

        return ProviderConnection(
            provider=self.name,
            status="connected" if connected else "disconnected",
            action_required=None if connected else ProviderErrorCode.API_KEY_REQUIRED,
            credential_type=credential_type,
            resolved_auth_mode=auth_mode if connected else None,
            key_source=key_source,
        )

    def _connection_from_error(self, credential_type: str, exc: Exception) -> ProviderConnection:
        action_required = provider_failure_code(exc)

        return ProviderConnection(
            provider=self.name,
            status="error",
            action_required=action_required,
            credential_type=credential_type,
        )


class LoginCapableProvider(AIProvider):
    # OAuth 로그인/로그아웃 흐름을 가진 provider(Claude CLI/Codex) 전용.
    @abstractmethod
    async def start_login(self) -> dict: ...

    @abstractmethod
    async def logout(self) -> None: ...

    async def submit_login_code(self, code: str) -> dict:
        raise ValueError(f"authorization code is not supported for provider: {self.name}")

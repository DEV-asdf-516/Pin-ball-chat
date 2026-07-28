from typing import AsyncIterator

from ai.specs import GenerateRequest, ProviderName
from ai.providers.base import AIProvider


class LocalStubProvider(AIProvider):
    name = ProviderName.LOCAL_STUB

    async def stream(self, _req: GenerateRequest) -> AsyncIterator[str]:
        text: str = "테스트 응답이야. 지금은 local-stub으로 대답하고 있어."
        for token in text.split(" "):
            yield token + " "

    async def list_models(self) -> list[str]:
        return ["local-stub"]

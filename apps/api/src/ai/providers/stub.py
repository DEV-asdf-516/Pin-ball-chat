from typing import AsyncIterator

from ai.model import GenerateRequest, GenerateResponse
from ai.providers.base import AIProvider


class LocalStubProvider(AIProvider):
    name = "local-stub"

    async def generate(self, req: GenerateRequest) -> GenerateResponse:
        text: str = f"{req.user_message} 테스트 메시지 생성이야."
        return GenerateResponse(text=text, provider=self.name, fallback_applied=False)

    async def stream(self, _req: GenerateRequest) -> AsyncIterator[str]:
        text: str = "테스트 응답이야. 지금은 local-stub으로 대답하고 있어."
        for token in text.split(" "):
            yield token + " "

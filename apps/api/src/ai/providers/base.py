from abc import ABC, abstractmethod
from typing import AsyncIterator

from ai.specs import GenerateRequest
from util.singleton import Singleton


class AIProvider(Singleton, ABC):
    """모든 AI provider(local-stub/ollama/openai/anthropic/gemini)가 따르는 공통 계약."""

    name: str

    @abstractmethod
    def stream(self, req: GenerateRequest) -> AsyncIterator[str]: ...

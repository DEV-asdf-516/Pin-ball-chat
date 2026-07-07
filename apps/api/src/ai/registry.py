from ai.settings import DEFAULT_AI_PROVIDER, DEFAULT_NUM_CTX, DEFAULT_NUM_PREDICT
from ai.model import GenerateRequest
from ai.providers.base import AIProvider
from ai.providers.anthropic import AnthropicProvider
from ai.providers.gemini import GeminiProvider
from ai.providers.ollama import OllamaProvider, is_qwen3_model, to_ollama_payload
from ai.providers.openai import OpenAIProvider
from ai.providers.stub import LocalStubProvider

_PROVIDERS: dict[str, AIProvider] = {
    "local-stub": LocalStubProvider(),
    "ollama": OllamaProvider(),
    "openai": OpenAIProvider(),
    "anthropic": AnthropicProvider(),
    "gemini": GeminiProvider(),
}


def resolve_provider(provider_name: str | None = None, model: str = "local-stub") -> AIProvider:
    if model == "local-stub":
        return _PROVIDERS["local-stub"]

    name: str = provider_name or DEFAULT_AI_PROVIDER

    provider: AIProvider | None = _PROVIDERS.get(name)

    if not provider:
        raise ValueError(f"unknown ai provider: {name}")

    return provider


def runtime_params(req: GenerateRequest, provider_name: str | None = None, fallback_applied: bool = False) -> dict:
    provider_name_resolved: str = resolve_provider(provider_name, req.model).name

    params: dict = {
        "model": req.model,
        "provider": provider_name_resolved,
        "maxTokens": req.num_predict or DEFAULT_NUM_PREDICT,
        "numCtx": req.num_ctx or DEFAULT_NUM_CTX,
        "fallbackApplied": fallback_applied,
        "disableThinking": False,
    }

    
    if provider_name_resolved == "ollama":
        payload: dict = to_ollama_payload(req)
        
        params.update({
            "keepAlive": payload["keep_alive"],
            "options": payload["options"],
            "stream": req.stream,
            "runtimeMessages": payload["messages"],
            "disableThinking": is_qwen3_model(req.model),
            "think": payload.get("think"),
        })

    return params


async def stream_text(req: GenerateRequest, provider_name: str | None = None):
    async for token in resolve_provider(provider_name, req.model).stream(req):
        yield token

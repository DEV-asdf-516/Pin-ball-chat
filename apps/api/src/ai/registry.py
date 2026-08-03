from ai.settings import DEFAULT_AI_PROVIDER, DEFAULT_NUM_CTX, DEFAULT_NUM_PREDICT
from ai.specs import GenerateRequest, PromptTier, ProviderName
from ai.providers.base import AIProvider
from ai.providers.anthropic import AnthropicProvider
from ai.providers.claude_cli import ClaudeCliProvider
from ai.providers.gemini import GeminiProvider
from ai.providers.ollama import OllamaProvider, to_ollama_payload
from ai.providers.openai import OpenAIProvider
from ai.providers.openai_codex import OpenAICodexProvider
from ai.providers.stub import LocalStubProvider

_PROVIDERS: dict[ProviderName, AIProvider] = {
    ProviderName.LOCAL_STUB: LocalStubProvider(),
    ProviderName.OLLAMA: OllamaProvider(),
    ProviderName.OPENAI: OpenAIProvider(),
    ProviderName.OPENAI_CODEX: OpenAICodexProvider(),
    ProviderName.ANTHROPIC: AnthropicProvider(),
    ProviderName.CLAUDE_CLI: ClaudeCliProvider(),
    ProviderName.GEMINI: GeminiProvider(),
}


def get_provider(provider_name: str) -> AIProvider | None:
    return _PROVIDERS.get(provider_name)


def resolve_provider(provider_name: str | None = None, model: str = "local-stub") -> AIProvider:
    if model == "local-stub":
        return _PROVIDERS[ProviderName.LOCAL_STUB]

    name: str = provider_name or DEFAULT_AI_PROVIDER

    provider: AIProvider | None = _PROVIDERS.get(name)

    if not provider:
        raise ValueError(f"unknown ai provider: {name}")

    return provider


def prompt_tier(provider_name: str | None, model: str) -> PromptTier:
    resolved: ProviderName = resolve_provider(provider_name, model).name
    if resolved in (ProviderName.OLLAMA, ProviderName.LOCAL_STUB):
        return PromptTier.LOCAL
    return PromptTier.EXTERNAL


def runtime_params(req: GenerateRequest, provider_name: str | None = None, fallback_applied: bool = False) -> dict:
    provider_name_resolved: ProviderName = resolve_provider(provider_name, req.model).name

    params: dict = {
        "model": req.model,
        "provider": provider_name_resolved,
        "maxTokens": req.num_predict or DEFAULT_NUM_PREDICT,
        "numCtx": req.num_ctx or DEFAULT_NUM_CTX,
        "fallbackApplied": fallback_applied,
        "disableThinking": False,
    }


    if provider_name_resolved == ProviderName.OLLAMA:
        payload: dict = to_ollama_payload(req)
        
        params.update({
            "keepAlive": payload["keep_alive"],
            "options": payload["options"],
            "stream": req.stream,
            "runtimeMessages": payload["messages"],
            "disableThinking": payload.get("think") is False,
            "think": payload.get("think"),
        })

    return params


async def stream_text(req: GenerateRequest, provider_name: str | None = None):
    async for token in resolve_provider(provider_name, req.model).stream(req):
        yield token


async def list_provider_models(provider_name: str) -> list[str]:
    provider: AIProvider | None = _PROVIDERS.get(provider_name)
    if not provider:
        raise ValueError(f"unknown ai provider: {provider_name}")
    return await provider.list_models()

from ai.constant import DEFAULT_AI_PROVIDER, DEFAULT_NUM_CTX, DEFAULT_NUM_PREDICT
from ai.provider import GenerateRequest
from ai.providers.ollama import OllamaProvider, is_qwen3_model, ollama_payload
from ai.providers.stub import LocalStubProvider

_PROVIDERS = {
    "local-stub": LocalStubProvider(),
    "ollama": OllamaProvider(),
}


def resolve_provider(provider_name=None, model="local-stub"):
    if model == "local-stub":
        return _PROVIDERS["local-stub"]
    name = provider_name or DEFAULT_AI_PROVIDER
    provider = _PROVIDERS.get(name)
    if not provider:
        raise ValueError(f"unknown ai provider: {name}")
    return provider


def runtime_params(provider_name, model, prompt, user_message, stream, num_predict=None, num_ctx=None, fallback_applied=False):
    provider_name_resolved = resolve_provider(provider_name, model).name
    params = {
        "model": model,
        "provider": provider_name_resolved,
        "maxTokens": num_predict or DEFAULT_NUM_PREDICT,
        "numCtx": num_ctx or DEFAULT_NUM_CTX,
        "fallbackApplied": fallback_applied,
        "disableThinking": False,
    }
    if provider_name_resolved == "ollama":
        payload = ollama_payload(model, prompt, user_message, stream, num_predict, num_ctx)
        params.update({
            "keepAlive": payload["keep_alive"],
            "options": payload["options"],
            "stream": stream,
            "runtimeMessages": payload["messages"],
            "disableThinking": is_qwen3_model(model),
            "think": payload.get("think"),
        })
    return params


def generate_text(prompt, user_message, model, candidate_index, num_predict=None, num_ctx=None, provider_name=None):
    req = GenerateRequest(prompt=prompt, user_message=user_message, model=model, candidate_index=candidate_index, num_predict=num_predict, num_ctx=num_ctx)
    return resolve_provider(provider_name, model).generate(req)


def stream_text(prompt, user_message, model, candidate_index, num_predict=None, num_ctx=None, provider_name=None):
    req = GenerateRequest(prompt=prompt, user_message=user_message, model=model, candidate_index=candidate_index, num_predict=num_predict, num_ctx=num_ctx)
    yield from resolve_provider(provider_name, model).stream(req)

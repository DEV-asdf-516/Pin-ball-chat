from typing import AsyncIterator
from urllib import parse

import httpx

from ai.settings import DEFAULT_NUM_PREDICT, GEMINI_BASE_URL, GEMINI_TEMPERATURE, GEMINI_TIMEOUT
from ai.errors import EmptyOutputError, ProviderBadGatewayError
from ai.transport.http_client import HttpClient
from ai.transport.http_errors import translate_http_errors
from ai.specs import GenerateRequest
from ai.providers.base import AIProvider
from ai.providers.timing import log_stream_timing
from ai.transport.sse import aiter_sse_events
from util.env_util import require_env
from util.safe_util import get_safe_dict, get_safe_list

_OK_FINISH_REASONS = ("STOP", "MAX_TOKENS", "FINISH_REASON_UNSPECIFIED")


def to_gemini_payload(req: GenerateRequest) -> dict:
    return {
        "system_instruction": {"parts": [{"text": req.system}]},
        "contents": [{"role": "model" if m.role == "assistant" else m.role, "parts": [{"text": m.content}]} for m in req.messages],
        "generationConfig": {
            "temperature": GEMINI_TEMPERATURE,
            "maxOutputTokens": req.num_predict or DEFAULT_NUM_PREDICT,
        },
    }


def _extract_candidate_text(event: dict) -> str:
    if event.get("error"):
        raise ProviderBadGatewayError(get_safe_dict(event, "error").get("message") or "gemini error")
    
    candidates: list = get_safe_list(event, "candidates")
    
    if not candidates:
        return ""
    candidate: dict = candidates[0]
    finish_reason: str | None = candidate.get("finishReason")
    
    if finish_reason and finish_reason not in _OK_FINISH_REASONS:
        raise ProviderBadGatewayError(f"gemini blocked: {finish_reason}")
    
    parts: list = get_safe_list(get_safe_dict(candidate, "content"), "parts")
    return "".join(part.get("text", "") for part in parts)


class GeminiProvider(AIProvider):
    name = "gemini"

    def _url(self, req: GenerateRequest, endpoint: str, extra_query: str = "") -> str:
        model_id: str = parse.quote(req.model, safe="")
        return f"{GEMINI_BASE_URL.rstrip('/')}/v1beta/models/{model_id}:{endpoint}?key={parse.quote(require_env('GEMINI_API_KEY'))}{extra_query}"

    @log_stream_timing
    async def stream(self, req: GenerateRequest) -> AsyncIterator[str]:
        emitted_text: str = ""
        url: str = self._url(req, "streamGenerateContent", extra_query="&alt=sse")
        client: httpx.AsyncClient = HttpClient().get()
        
        async with (
            client.stream("POST", url, json=to_gemini_payload(req), timeout=GEMINI_TIMEOUT) as res,
            translate_http_errors(self.name),
        ):
            res: httpx.Response
            res.raise_for_status()
            emitted_content: bool = False

            async for event in aiter_sse_events(res):
                text: str = _extract_candidate_text(event)
                if not text:
                    continue
                delta: str = text[len(emitted_text):] if text.startswith(emitted_text) else text

                emitted_text = text

                if delta:
                    emitted_content = True
                    yield delta

            if not emitted_content:
                raise EmptyOutputError("gemini produced no content")

    async def list_models(self) -> list[str]:
        url: str = f"{GEMINI_BASE_URL.rstrip('/')}/v1beta/models?key={parse.quote(require_env('GEMINI_API_KEY'))}"
        client: httpx.AsyncClient = HttpClient().get()
        async with translate_http_errors(self.name):
            res: httpx.Response = await client.get(url, timeout=GEMINI_TIMEOUT)
            res.raise_for_status()
            return [m["name"].removeprefix("models/") for m in res.json().get("models", [])]

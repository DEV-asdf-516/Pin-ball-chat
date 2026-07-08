import os
from typing import AsyncIterator

import httpx

from ai.settings import ANTHROPIC_API_VERSION, ANTHROPIC_BASE_URL, ANTHROPIC_TEMPERATURE, ANTHROPIC_TIMEOUT, DEFAULT_NUM_PREDICT
from ai.errors import EmptyOutputError, ProviderBadGatewayError
from ai.transport.http_client import HttpClient
from ai.transport.http_errors import translate_http_errors
from ai.specs import GenerateRequest
from ai.providers.base import AIProvider
from ai.transport.sse import aiter_sse_events
from util.safe_util import get_safe_dict


_ENDPOINT = ANTHROPIC_BASE_URL.rstrip("/") + "/v1/messages"


def _api_key() -> str:
    api_key: str | None = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is missing")
    return api_key


def to_anthropic_payload(req: GenerateRequest) -> dict:
    return {
        "model": req.model,
        "system": req.system,
        "messages": [{"role": m.role, "content": m.content} for m in req.messages],
        "max_tokens": req.num_predict or DEFAULT_NUM_PREDICT,
        "temperature": ANTHROPIC_TEMPERATURE,
        "stream": req.stream,
    }


class AnthropicProvider(AIProvider):
    name = "anthropic"

    def _headers(self) -> dict:
        return {
            "anthropic-version": ANTHROPIC_API_VERSION,
            "content-type": "application/json",
            "x-api-key": _api_key(),
        }

    async def stream(self, req: GenerateRequest) -> AsyncIterator[str]:
        payload: dict = to_anthropic_payload(req)
        client: httpx.AsyncClient = HttpClient().get()
        async with (
            translate_http_errors(self.name),
            client.stream("POST", _ENDPOINT, json=payload, headers=self._headers(), timeout=ANTHROPIC_TIMEOUT) as res,
        ):
            res: httpx.Response
            res.raise_for_status()
            emitted_content: bool = False
            async for event in aiter_sse_events(res):
                if event.get("type") == "error":
                    err: dict = get_safe_dict(event, "error")
                    raise ProviderBadGatewayError(err.get("message") or "anthropic stream error")

                if event.get("type") != "content_block_delta":
                    continue
                delta: dict = get_safe_dict(event, "delta")

                if delta.get("type") != "text_delta" or not delta.get("text"):
                    continue

                emitted_content = True
                yield delta["text"]

            if not emitted_content:
                raise EmptyOutputError("anthropic produced no content")

import os
from typing import AsyncIterator

import httpx

from ai.settings import DEFAULT_NUM_PREDICT, OPENAI_BASE_URL, OPENAI_TEMPERATURE, OPENAI_TIMEOUT
from ai.errors import EmptyOutputError, ProviderBadGatewayError
from ai.transport.http_client import HttpClient
from ai.transport.http_errors import translate_http_errors
from ai.specs import GenerateRequest
from ai.providers.base import AIProvider
from ai.transport.sse import aiter_sse_events
from util.safe_util import get_safe_dict


_ENDPOINT = OPENAI_BASE_URL.rstrip("/") + "/v1/responses"


def _api_key() -> str:
    api_key: str | None = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is missing")
    return api_key


def to_openai_payload(req: GenerateRequest) -> dict:
    return {
        "model": req.model,
        "instructions": req.system,
        "input": [{"role": m.role, "content": m.content} for m in req.messages],
        "max_output_tokens": req.num_predict or DEFAULT_NUM_PREDICT,
        "temperature": OPENAI_TEMPERATURE,
        "stream": req.stream,
    }


class OpenAIProvider(AIProvider):
    name = "openai"

    def _headers(self) -> dict:
        return {"Content-Type": "application/json", "Authorization": f"Bearer {_api_key()}"}

    async def stream(self, req: GenerateRequest) -> AsyncIterator[str]:
        payload: dict = to_openai_payload(req)
        client: httpx.AsyncClient = HttpClient().get()
        
        async with (
            client.stream("POST", _ENDPOINT, json=payload, headers=self._headers(), timeout=OPENAI_TIMEOUT) as res,
            translate_http_errors(self.name),
        ):
            res: httpx.Response
            res.raise_for_status()
            emitted_content: bool = False
            async for event in aiter_sse_events(res):
                event_type: str | None = event.get("type")

                if event_type == "error":
                    raise ProviderBadGatewayError(event.get("message") or "openai stream error")

                if event_type == "response.failed":
                    err: dict = get_safe_dict(get_safe_dict(event, "response"), "error")
                    raise ProviderBadGatewayError(err.get("message") or "openai request failed")

                if event_type != "response.output_text.delta" or not event.get("delta"):
                    continue

                emitted_content = True
                yield event["delta"]

            if not emitted_content:
                raise EmptyOutputError("openai produced no content")

    async def list_models(self) -> list[str]:
        url: str = OPENAI_BASE_URL.rstrip("/") + "/v1/models"
        client: httpx.AsyncClient = HttpClient().get()
        async with translate_http_errors(self.name):
            res: httpx.Response = await client.get(url, headers=self._headers(), timeout=OPENAI_TIMEOUT)
            res.raise_for_status()
            return [m["id"] for m in res.json().get("data", [])]

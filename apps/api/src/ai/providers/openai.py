import os
from typing import AsyncIterator

import httpx

from ai.settings import DEFAULT_NUM_PREDICT, OPENAI_BASE_URL, OPENAI_TEMPERATURE, OPENAI_TIMEOUT
from ai.errors import EmptyOutputError, ProviderBadGatewayError
from ai.transport.http_client import HttpClient
from ai.transport.http_errors import translate_http_errors
from ai.model import GenerateRequest, GenerateResponse
from ai.providers.base import AIProvider
from ai.transport.sse import aiter_sse_events
from util.dict_util import get_safe_dict, get_safe_list


_ENDPOINT = OPENAI_BASE_URL.rstrip("/") + "/v1/responses"


def _api_key() -> str:
    api_key: str | None = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is missing")
    return api_key


def to_openai_payload(req: GenerateRequest) -> dict:
    return {
        "model": req.model,
        "instructions": req.prompt,
        "input": [{"role": "user", "content": req.user_message}],
        "max_output_tokens": req.num_predict or DEFAULT_NUM_PREDICT,
        "temperature": OPENAI_TEMPERATURE,
        "stream": req.stream,
    }


def _extract_output_text(body: dict) -> str:
    output_text: str | None = body.get("output_text")
    if output_text:
        return output_text
    parts: list[str] = [
        content_item["text"]
        for item in get_safe_list(body, "output")
        for content_item in get_safe_list(item, "content")
        if content_item.get("text")
    ]
    return "".join(parts)


class OpenAIProvider(AIProvider):
    name = "openai"

    def _headers(self) -> dict:
        return {"Content-Type": "application/json", "Authorization": f"Bearer {_api_key()}"}

    async def generate(self, req: GenerateRequest) -> GenerateResponse:
        payload: dict = to_openai_payload(req)
        client: httpx.AsyncClient = HttpClient().get()
        async with translate_http_errors(self.name):
            res: httpx.Response = await client.post(_ENDPOINT, json=payload, headers=self._headers(), timeout=OPENAI_TIMEOUT)
            res.raise_for_status()
            body: dict = res.json()

        content: str = _extract_output_text(body)
        if not content:
            raise EmptyOutputError("openai produced no content")
        return GenerateResponse(text=content, provider=self.name)

    async def stream(self, req: GenerateRequest) -> AsyncIterator[str]:
        payload: dict = to_openai_payload(req)
        client: httpx.AsyncClient = HttpClient().get()
        
        async with (
            translate_http_errors(self.name),
            client.stream("POST", _ENDPOINT, json=payload, headers=self._headers(), timeout=OPENAI_TIMEOUT) as res,
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

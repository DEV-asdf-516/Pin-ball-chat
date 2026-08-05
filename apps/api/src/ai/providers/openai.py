from typing import AsyncIterator

import httpx

from ai.settings import DEFAULT_NUM_PREDICT, OPENAI_BASE_URL, OPENAI_TEMPERATURE, OPENAI_TIMEOUT
from ai.errors import EmptyOutputError, ProviderErrorCode, ProviderRuntimeError, classify_provider_error
from ai.transport.http_client import HttpClient
from ai.transport.http_errors import translate_http_errors
from ai.specs import GenerateRequest, ProviderConnection, ProviderName
from ai.providers.base import AIProvider
from ai.providers.timing import log_stream_timing
from ai.transport.sse import aiter_sse_events
from ai.auth.api_key_store import resolve_api_key
from util.safe_util import get_safe_dict, get_safe_str


_ENDPOINT = OPENAI_BASE_URL.rstrip("/") + "/v1/responses"

_PROHIBITED_ITEM_TYPES = {"function_call", "computer_call", "file_search_call", "web_search_call", "mcp_call"}
_PROHIBITED_EVENT_TYPES = {"response.function_call_arguments.delta", "response.mcp_call_arguments.delta"}


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
    name = ProviderName.OPENAI

    def _headers(self) -> dict:
        return {"Content-Type": "application/json", "Authorization": f"Bearer {resolve_api_key('OPENAI_API_KEY')}"}

    @log_stream_timing
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
                event_type: str = get_safe_str(event, "type")

                item: dict = get_safe_dict(event, "item")
                
                if item.get("type") in _PROHIBITED_ITEM_TYPES or event_type in _PROHIBITED_EVENT_TYPES:
                    raise ProviderRuntimeError(ProviderErrorCode.PROVIDER_CONTRACT_VIOLATION, "OpenAI attempted a prohibited tool action", self.name)

                if event_type == "error":
                    error: dict = event.get("error") if isinstance(event.get("error"), dict) else event
                    raise classify_provider_error(self.name, error)

                if event_type == "response.failed":
                    failed: dict = get_safe_dict(get_safe_dict(event, "response"), "error")
                    raise classify_provider_error(self.name, failed)

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

    async def connection(self) -> ProviderConnection:
        return self._api_key_connection(credential_type="authorization_key", auth_mode="openai_api_key", env_name="OPENAI_API_KEY")

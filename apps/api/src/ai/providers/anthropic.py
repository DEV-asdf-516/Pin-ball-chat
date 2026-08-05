from typing import AsyncIterator

import httpx

from ai.settings import ANTHROPIC_API_VERSION, ANTHROPIC_BASE_URL, ANTHROPIC_TEMPERATURE, ANTHROPIC_TIMEOUT, DEFAULT_NUM_PREDICT
from ai.errors import EmptyOutputError, ProviderErrorCode, ProviderRuntimeError, classify_provider_error
from ai.transport.http_client import HttpClient
from ai.transport.http_errors import translate_http_errors
from ai.specs import GenerateRequest, ProviderConnection, ProviderName
from ai.providers.base import AIProvider
from ai.providers.timing import log_stream_timing
from ai.transport.sse import aiter_sse_events
from ai.auth.api_key_store import resolve_api_key
from util.safe_util import get_safe_dict, get_safe_str


_ENDPOINT = ANTHROPIC_BASE_URL.rstrip("/") + "/v1/messages"


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
    name = ProviderName.ANTHROPIC

    def _headers(self) -> dict:
        return {
            "anthropic-version": ANTHROPIC_API_VERSION,
            "content-type": "application/json",
            "x-api-key": resolve_api_key("ANTHROPIC_API_KEY"),
        }

    @log_stream_timing
    async def stream(self, req: GenerateRequest) -> AsyncIterator[str]:
        payload: dict = to_anthropic_payload(req)
        client: httpx.AsyncClient = HttpClient().get()
        async with (client.stream("POST", _ENDPOINT, json=payload, headers=self._headers(), timeout=ANTHROPIC_TIMEOUT) as res,translate_http_errors(self.name)):
            res: httpx.Response
            res.raise_for_status()
            emitted_content: bool = False
            
            async for event in aiter_sse_events(res):
                event_type: str = get_safe_str(event, "type")

                if event_type == "error":
                    err: dict = get_safe_dict(event, "error")
                    raise classify_provider_error(self.name, err)

                if event_type== "content_block_start":
                    block: dict = get_safe_dict(event, "content_block")
                    
                    if block.get("type") in {"tool_use", "server_tool_use"}:
                        raise ProviderRuntimeError(
                            ProviderErrorCode.PROVIDER_CONTRACT_VIOLATION, 
                            "Anthropic attempted a prohibited tool action", 
                            self.name
                        )

                    continue

                if event_type != "content_block_delta":
                    continue

                delta: dict = get_safe_dict(event, "delta")
                text: str = delta.get("text")

                if delta.get("type") != "text_delta" or not text:
                    continue

                emitted_content = True
                yield text

            if not emitted_content:
                raise EmptyOutputError("anthropic produced no content")

    async def list_models(self) -> list[str]:
        url: str = ANTHROPIC_BASE_URL.rstrip("/") + "/v1/models"
        
        client: httpx.AsyncClient = HttpClient().get()
        
        async with translate_http_errors(self.name):
            res: httpx.Response = await client.get(url, headers=self._headers(), timeout=ANTHROPIC_TIMEOUT)
            res.raise_for_status()
            return [m["id"] for m in res.json().get("data", [])]

    async def connection(self) -> ProviderConnection:
        return self._api_key_connection(credential_type="authorization_key", auth_mode="anthropic_api_key", env_name="ANTHROPIC_API_KEY")

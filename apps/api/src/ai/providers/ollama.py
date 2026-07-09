import json
import os
from dataclasses import replace
from typing import AsyncIterator

import httpx

from ai.settings import DEFAULT_NUM_CTX, DEFAULT_NUM_PREDICT, OLLAMA_KEEP_ALIVE, OLLAMA_OPTIONS, OLLAMA_TIMEOUT
from ai.errors import EmptyOutputError
from ai.transport.http_client import HttpClient
from ai.transport.http_errors import translate_http_errors
from ai.specs import GenerateRequest
from ai.providers.base import AIProvider
from util.safe_util import get_safe_dict


def is_qwen3_model(model: str) -> bool:
    return model.lower().startswith("qwen3")


def _is_bad_gateway(exc: httpx.HTTPStatusError, body: str) -> bool:
    return exc.response.status_code in (400, 404) or "model" in body.lower()


def _is_qwen3_response_empty(model: str, has_content) -> bool:
    return is_qwen3_model(model) and not has_content


def _base_url() -> str:
    base_url: str | None = os.environ.get("OLLAMA_BASE_URL")
    if not base_url:
        raise ValueError("OLLAMA_BASE_URL is missing")
    return base_url


def to_ollama_payload(req: GenerateRequest) -> dict:
    options: dict = {
        **OLLAMA_OPTIONS,
        "num_predict": req.num_predict or DEFAULT_NUM_PREDICT,
        "num_ctx": req.num_ctx or DEFAULT_NUM_CTX,
    }

    payload: dict = {
        "model": req.model,
        "stream": req.stream,
        "think": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": options,
        "messages": [
            {"role": "system", "content": req.system},
            *({"role": m.role, "content": m.content} for m in req.messages),
        ],
    }

    return payload


class OllamaProvider(AIProvider):
    name = "ollama"

    async def stream(self, req: GenerateRequest) -> AsyncIterator[str]:
        async for token in self._stream_internal(req, retried=False):
            yield token

    async def _stream_internal(self, req: GenerateRequest, retried: bool) -> AsyncIterator[str]:
        payload: dict = to_ollama_payload(req)
        url: str = _base_url().rstrip("/") + "/api/chat"
        client: httpx.AsyncClient = HttpClient().get()

        async with (
            translate_http_errors("ollama", _is_bad_gateway),
            client.stream("POST", url, json=payload, timeout=OLLAMA_TIMEOUT) as res,
        ):
            res: httpx.Response
            res.raise_for_status()
            emitted_content: bool = False
            async for line in res.aiter_lines():
                if not line.strip():
                    continue
                
                chunk: dict = json.loads(line)
                content: str | None = get_safe_dict(chunk, "message").get("content")
                
                if content:
                    emitted_content = True
                    yield content
                
                if not chunk.get("done"):
                    continue
                
                if _is_qwen3_response_empty(req.model, emitted_content):
                    if not retried:
                        fallback_tokens: int = max(req.num_predict or DEFAULT_NUM_PREDICT, 256)
                        async for token in self._stream_internal(replace(req, num_predict=fallback_tokens), True):
                            yield token
                        return
                    raise EmptyOutputError("qwen3 produced no content with think:false")

                if not emitted_content:
                    raise EmptyOutputError("ollama produced no content")
                return

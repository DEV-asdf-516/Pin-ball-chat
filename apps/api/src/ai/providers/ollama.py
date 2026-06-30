import json
import logging
import os
import socket
from dataclasses import replace
from urllib import error, request

log = logging.getLogger(__name__)

from ai.constant import DEFAULT_NUM_CTX, DEFAULT_NUM_PREDICT, OLLAMA_KEEP_ALIVE, OLLAMA_OPTIONS, OLLAMA_TIMEOUT
from ai.errors import EmptyOutputError, OllamaBadGatewayError, OllamaTimeoutError
from ai.provider import GenerateRequest
from ai.providers.stub import LocalStubProvider


def is_qwen3_model(model: str) -> bool:
    return model.lower().startswith("qwen3")


def ollama_payload(model, prompt, user_message, stream, num_predict=None, num_ctx=None):
    options = {**OLLAMA_OPTIONS, "num_predict": num_predict or DEFAULT_NUM_PREDICT, "num_ctx": num_ctx or DEFAULT_NUM_CTX}
    payload = {
        "model": model,
        "stream": stream,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": options,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_message},
        ],
    }
    if is_qwen3_model(model):
        payload["think"] = False
    return payload


class OllamaProvider:
    name = "ollama"
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def generate(self, req: GenerateRequest, retried=False):
        base_url = os.environ.get("OLLAMA_BASE_URL")

        if not base_url:
            text, _ = LocalStubProvider().generate(req)
            return text, {"provider": "local-stub", "fallbackApplied": True}

        payload = ollama_payload(req.model, req.prompt, req.user_message, False, req.num_predict, req.num_ctx)
        log.debug("→ ollama generate | model=%s think=%s num_predict=%s\n[PROMPT]\n%s\n[USER]\n%s",
                  req.model, payload.get("think"), payload["options"].get("num_predict"),
                  req.prompt, req.user_message)

        http_req = request.Request(
            base_url.rstrip("/") + "/api/chat",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with request.urlopen(http_req, timeout=OLLAMA_TIMEOUT) as res:
                body = json.loads(res.read())
        except (TimeoutError, socket.timeout) as exc:
            raise OllamaTimeoutError("ollama request timed out") from exc
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code in (400, 404) or "model" in body.lower():
                raise OllamaBadGatewayError(f"ollama returned {exc.code}: {body}") from exc
            raise

        content = body.get("message", {}).get("content") or body.get("response") or ""
        log.debug("← ollama generate | content_len=%d retried=%s\n[RAW_CONTENT]\n%s", len(content), retried, content[:400])

        if not content and is_qwen3_model(req.model) and not retried:
            fallback_tokens = max(req.num_predict or DEFAULT_NUM_PREDICT, 256)
            text, meta = self.generate(replace(req, num_predict=fallback_tokens), True)
            meta["fallbackApplied"] = True
            return text, meta

        if not content and is_qwen3_model(req.model):
            raise EmptyOutputError("qwen3 produced no content with think:false")

        if not content:
            text, _ = LocalStubProvider().generate(req)
            return text, {"provider": self.name, "fallbackApplied": retried}
        return content, {"provider": self.name, "fallbackApplied": retried}

    def stream(self, req: GenerateRequest, retried=False):
        base_url = os.environ.get("OLLAMA_BASE_URL")
        if not base_url:
            yield from LocalStubProvider().stream(req)
            return
        payload = ollama_payload(req.model, req.prompt, req.user_message, True, req.num_predict, req.num_ctx)
        http_req = request.Request(
            base_url.rstrip("/") + "/api/chat",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(http_req, timeout=OLLAMA_TIMEOUT) as res:
                emitted_content = False
                for raw in res:
                    if not raw.strip():
                        continue
                    chunk = json.loads(raw)
                    content = chunk.get("message", {}).get("content")
                    if content:
                        emitted_content = True
                        yield content
                    if chunk.get("done"):
                        if is_qwen3_model(req.model) and not emitted_content and not retried:
                            fallback_tokens = max(req.num_predict or DEFAULT_NUM_PREDICT, 256)
                            yield from self.stream(replace(req, num_predict=fallback_tokens), True)
                            return
                        if is_qwen3_model(req.model) and not emitted_content:
                            raise EmptyOutputError("qwen3 produced no content with think:false")
                        return
        except (TimeoutError, socket.timeout) as exc:
            raise OllamaTimeoutError("ollama stream timed out") from exc
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code in (400, 404) or "model" in body.lower():
                raise OllamaBadGatewayError(f"ollama returned {exc.code}: {body}") from exc
            raise

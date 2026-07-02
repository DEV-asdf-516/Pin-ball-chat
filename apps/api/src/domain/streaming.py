import json
import logging
from typing import Iterator

from ai.errors import EmptyOutputError, OllamaBadGatewayError, OllamaTimeoutError
from ai.registry import stream_text
from core.db import connect, init_db
from domain.generation_params import GenerationParams
from domain.generations import insert_user_turn, mark_regenerated, save_generation_output
from domain.prompts import BuiltPrompt

log = logging.getLogger(__name__)


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def stream_response(prepared: dict, params: GenerationParams) -> Iterator[str]:
    full_text: list[str] = []
    built: BuiltPrompt = prepared["built"]
    try:
        yield sse("start", {"conversationId": prepared["conversationId"], "turnId": prepared["turnId"]})
        for token in stream_text(built.prompt, prepared["userMessage"], params.model, 0, params.num_predict, params.num_ctx, params.provider_name):
            full_text.append(token)
            yield sse("token", {"content": token})
        output: str = "".join(full_text)
        with connect() as conn:
            init_db(conn)
            if "messageId" in prepared:
                insert_user_turn(conn, prepared["conversationId"], prepared["userMessage"], prepared["messageId"], prepared["turnId"], prepared["createdAt"])
            if prepared.get("currentGenerationId"):
                mark_regenerated(conn, prepared["conversationId"], prepared["turnId"], prepared["currentGenerationId"])
            saved: dict = save_generation_output(
                conn,
                prepared["turnId"],
                prepared["conversationId"],
                built,
                params,
                output,
                prepared["actionType"],
                None,
                True,
            )
        yield sse("done", {
            "conversationId": prepared["conversationId"],
            "turnId": prepared["turnId"],
            "generationId": saved["generationId"],
            "messageId": saved["messageId"],
        })
    except GeneratorExit:
        log.info("stream aborted: turn_id=%s", prepared["turnId"])
    except OllamaTimeoutError as exc:
        log.exception("ollama timeout during stream")
        yield sse("error", {"error": "ollama_timeout", "message": str(exc)})
    except OllamaBadGatewayError as exc:
        log.exception("ollama bad gateway during stream")
        yield sse("error", {"error": "ollama_bad_gateway", "message": str(exc)})
    except EmptyOutputError as exc:
        yield sse("error", {"error": "empty_output", "message": str(exc)})
    except Exception as exc:
        log.exception("unexpected error during stream")
        yield sse("error", {"error": "internal_error", "message": str(exc)})

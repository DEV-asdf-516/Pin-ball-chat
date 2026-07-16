import json
import logging
from typing import AsyncIterator

from ai.errors import EmptyOutputError, ProviderBadGatewayError, ProviderTimeoutError
from ai.registry import stream_text
from ai.specs import GenerateRequest
from core.db import connect, init_db
from domain.specs import GenerationParams
from domain.turns.specs import PreparedGeneration
from domain.turns.writer import create_user_turn, record_generation_output, start_regeneration

log = logging.getLogger(__name__)


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def stream_response(prepared: PreparedGeneration, params: GenerationParams) -> AsyncIterator[str]:
    full_text: list[str] = []
    req = GenerateRequest(
        system=prepared.built.system,
        messages=prepared.built.messages,
        model=params.model,
        candidate_index=0,
        num_predict=params.num_predict,
        num_ctx=params.num_ctx,
        stream=True,
    )
    try:
        yield sse("start", {
            "conversationId": prepared.conversation_id,
            "turnId": prepared.turn_id,
            "messageId": prepared.message_id}
        )

        async for token in stream_text(req, params.provider_name):
            full_text.append(token)
            yield sse("token", {"content": token})

        output: str = "".join(full_text)

        with connect() as conn:
            init_db(conn)

            if prepared.message_id:
                create_user_turn(conn, prepared)

            if prepared.current_generation_id:
                start_regeneration(conn, prepared)

            saved: dict = record_generation_output(conn, prepared, params, req, output)

        yield sse(
            "done", {
            "conversationId": prepared.conversation_id,
            "turnId": prepared.turn_id,
            "generationId": saved["generationId"],
            "messageId": saved["messageId"],
        })

    except GeneratorExit:
        log.info("stream aborted: turn_id=%s", prepared.turn_id)
    except ProviderTimeoutError as exc:
        log.exception("provider timeout during stream")
        yield sse("error", {"error": "provider_timeout", "message": str(exc)})
    except ProviderBadGatewayError as exc:
        log.exception("provider bad gateway during stream")
        yield sse("error", {"error": "provider_bad_gateway", "message": str(exc)})
    except EmptyOutputError as exc:
        yield sse("error", {"error": "empty_output", "message": str(exc)})
    except Exception as exc:
        log.exception("unexpected error during stream")
        yield sse("error", {"error": "internal_error", "message": str(exc)})

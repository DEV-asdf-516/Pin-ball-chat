import json
import traceback

from ai.errors import EmptyOutputError, OllamaBadGatewayError, OllamaTimeoutError
from ai.registry import stream_text
from core.db import connect, init_db
from domain.services import GenerationParams, insert_user_turn, mark_regenerated, save_generation_output


def sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def stream_response(prepared, params: GenerationParams):
    full_text = []
    try:
        yield sse("start", {"conversationId": prepared["conversationId"], "turnId": prepared["turnId"]})
        for token in stream_text(prepared["prompt"], prepared["userMessage"], params.model, 0, params.num_predict, params.num_ctx, params.provider_name):
            full_text.append(token)
            yield sse("token", {"content": token})
        output = "".join(full_text)
        with connect() as conn:
            init_db(conn)
            if "messageId" in prepared:
                insert_user_turn(conn, prepared["conversationId"], prepared["userMessage"], prepared["messageId"], prepared["turnId"], prepared["createdAt"])
            if prepared.get("currentGenerationId"):
                mark_regenerated(conn, prepared["conversationId"], prepared["turnId"], prepared["currentGenerationId"])
            saved = save_generation_output(
                conn,
                prepared["turnId"],
                prepared["conversationId"],
                prepared["plot"],
                prepared["char"],
                prepared["user"],
                params,
                prepared["prompt"],
                prepared["warnings"],
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
        print(f"stream aborted: turn_id={prepared['turnId']}")
    except OllamaTimeoutError as exc:
        traceback.print_exception(type(exc), exc, exc.__traceback__)
        yield sse("error", {"error": "ollama_timeout", "message": str(exc)})
    except OllamaBadGatewayError as exc:
        traceback.print_exception(type(exc), exc, exc.__traceback__)
        yield sse("error", {"error": "ollama_bad_gateway", "message": str(exc)})
    except EmptyOutputError as exc:
        yield sse("error", {"error": "empty_output", "message": str(exc)})
    except Exception as exc:
        traceback.print_exception(type(exc), exc, exc.__traceback__)
        yield sse("error", {"error": "internal_error", "message": str(exc)})

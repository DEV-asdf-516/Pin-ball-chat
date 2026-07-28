import asyncio
import json
import logging
from typing import AsyncIterator, Callable

from ai.errors import EmptyOutputError, ProviderBadGatewayError, ProviderErrorCode, ProviderRuntimeError, ProviderTimeoutError
from ai.registry import resolve_provider, stream_text
from ai.specs import GenerateRequest
from ai.settings import SSE_HEARTBEAT_SECONDS
from core.db import connect, init_db, session
from domain.specs import GenerationParams
from domain.turns.specs import PreparedGeneration
from domain.turns.writer import create_user_turn, record_generation_output, start_regeneration

log = logging.getLogger(__name__)


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def stream_response(prepared: PreparedGeneration, params: GenerationParams, after_success: Callable[[], None] | None = None) -> AsyncIterator[str]:
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
    token_stream = None
    token_task = None
    terminal_sent = False
    provider_name: str  = params.provider_name or "unknown"
    try:
        provider_name = resolve_provider(params.provider_name, params.model).name
        yield sse("start", {
            "conversationId": prepared.conversation_id,
            "turnId": prepared.turn_id,
            "messageId": prepared.message_id}
        )

        token_stream = stream_text(req, provider_name).__aiter__()
        token_task = asyncio.create_task(anext(token_stream))
        while True:
            done, _ = await asyncio.wait({token_task}, timeout=SSE_HEARTBEAT_SECONDS)
            if not done:
                yield ": ping\n\n"
                continue
            try:
                token = token_task.result()
            except StopAsyncIteration:
                break
            full_text.append(token)
            yield sse("token", {"content": token})
            token_task = asyncio.create_task(anext(token_stream))

        output: str = "".join(full_text)

        with session(connect) as conn:
            init_db(conn)

            if prepared.message_id:
                create_user_turn(conn, prepared)

            if prepared.current_generation_id:
                start_regeneration(conn, prepared)

            saved: dict = record_generation_output(conn, prepared, params, req, output)

        if after_success:
            after_success()
        terminal_sent = True
        yield sse(
            "done", {
            "conversationId": prepared.conversation_id,
            "turnId": prepared.turn_id,
            "generationId": saved["generationId"],
            "messageId": saved["messageId"],
        })
    except GeneratorExit:
        log.info("stream aborted: turn_id=%s", prepared.turn_id)
        raise
    except asyncio.CancelledError:
        log.info("stream cancelled: turn_id=%s", prepared.turn_id)
        raise
    except ProviderTimeoutError as exc:
        if not terminal_sent:
            payload = {"error": ProviderErrorCode.PROVIDER_TIMEOUT, "code": ProviderErrorCode.PROVIDER_TIMEOUT, "provider": exc.provider or provider_name, "message": str(exc), "retryable": True}
            if exc.phase:
                payload["phase"] = exc.phase
            terminal_sent = True
            yield sse("error", payload)
    except ProviderRuntimeError as exc:
        if not terminal_sent:
            payload = {"error": exc.code, "code": exc.code, "provider": exc.provider, "message": str(exc), "retryable": exc.retryable}
            if exc.phase:
                payload["phase"] = exc.phase
            terminal_sent = True
            yield sse("error", payload)
    except ProviderBadGatewayError as exc:
        if not terminal_sent:
            terminal_sent = True
            yield sse("error", {"error": ProviderErrorCode.PROVIDER_BAD_GATEWAY, "code": ProviderErrorCode.PROVIDER_BAD_GATEWAY, "provider": exc.provider or provider_name, "message": str(exc), "retryable": True})
    except EmptyOutputError as exc:
        if not terminal_sent:
            terminal_sent = True
            yield sse("error", {"error": ProviderErrorCode.PROVIDER_BAD_GATEWAY, "code": ProviderErrorCode.PROVIDER_BAD_GATEWAY, "provider": provider_name, "message": str(exc), "retryable": False})
    except Exception as exc:
        log.exception("unexpected error during stream")
        if not terminal_sent:
            terminal_sent = True
            yield sse("error", {"error": ProviderErrorCode.PROVIDER_BAD_GATEWAY, "code": ProviderErrorCode.PROVIDER_BAD_GATEWAY, "provider": provider_name, "message": "generation failed", "retryable": True})
    finally:
        if token_task:
            if not token_task.done():
                token_task.cancel()
            try:
                token_task.result() if token_task.done() else await token_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        if token_stream:
            try:
                await token_stream.aclose()
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

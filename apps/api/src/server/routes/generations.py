from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from domain.turns.writer import edit_generation, prepare_chat_stream, prepare_regenerate_stream, select_generation
from domain.turns.streaming import stream_response
from server.dependencies import DbConn
from server.specs import ChatRequest, EditGenerationRequest, EditResponse, RegenerateRequest, SelectResponse


router = APIRouter()


@router.post("/api/chat/stream", description="Returns Server-Sent Events. Use curl -N or browser fetch streaming client.")
def post_chat_stream(body: ChatRequest, conn: DbConn):
    prepared = prepare_chat_stream(conn, body.conversation_id, body.message)
    return StreamingResponse(stream_response(prepared, body.to_params()), media_type="text/event-stream")


@router.post("/api/turns/{turn_id}/regenerate/stream", description="Returns Server-Sent Events. Use curl -N or browser fetch streaming client.")
def post_regenerate_stream(turn_id: str, conn: DbConn, body: RegenerateRequest | None = None):
    body = body or RegenerateRequest()
    prepared = prepare_regenerate_stream(conn, turn_id)
    return StreamingResponse(stream_response(prepared, body.to_params()), media_type="text/event-stream")


@router.post("/api/generations/{generation_id}/select", response_model=SelectResponse)
def post_select(generation_id: str, conn: DbConn):
    return select_generation(conn, generation_id)


@router.post("/api/generations/{generation_id}/edit", response_model=EditResponse)
def post_edit(generation_id: str, body: EditGenerationRequest, conn: DbConn):
    return edit_generation(conn, generation_id, body.edited_text)

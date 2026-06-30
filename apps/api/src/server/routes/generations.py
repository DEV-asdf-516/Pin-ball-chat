from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from domain.services import chat, edit_generation, prepare_chat_stream, prepare_regenerate_stream, regenerate, select_generation
from domain.streaming import stream_response
from server.routes._helpers import db_business
from server.schemas import ChatRequest, ChatResponse, EditGenerationRequest, EditResponse, RegenerateRequest, SelectResponse


router = APIRouter()


@router.post("/api/chat", response_model=ChatResponse)
def post_chat(body: ChatRequest):
    return db_business(lambda conn: chat(conn, body.conversation_id, body.message, body.to_params()))


@router.post("/api/chat/stream", description="Returns Server-Sent Events. Use curl -N or browser fetch streaming client.")
def post_chat_stream(body: ChatRequest):
    prepared = db_business(lambda conn: prepare_chat_stream(conn, body.conversation_id, body.message))
    return StreamingResponse(stream_response(prepared, body.to_params()), media_type="text/event-stream")


@router.post("/api/turns/{turn_id}/regenerate", response_model=ChatResponse)
def post_regenerate(turn_id: str, body: RegenerateRequest | None = None):
    body = body or RegenerateRequest()
    return db_business(lambda conn: regenerate(conn, turn_id, body.to_params()))


@router.post("/api/turns/{turn_id}/regenerate/stream", description="Returns Server-Sent Events. Use curl -N or browser fetch streaming client.")
def post_regenerate_stream(turn_id: str, body: RegenerateRequest | None = None):
    body = body or RegenerateRequest()
    prepared = db_business(lambda conn: prepare_regenerate_stream(conn, turn_id))
    return StreamingResponse(stream_response(prepared, body.to_params()), media_type="text/event-stream")


@router.post("/api/generations/{generation_id}/select", response_model=SelectResponse)
def post_select(generation_id: str):
    return db_business(lambda conn: select_generation(conn, generation_id))


@router.post("/api/generations/{generation_id}/edit", response_model=EditResponse)
def post_edit(generation_id: str, body: EditGenerationRequest):
    return db_business(lambda conn: edit_generation(conn, generation_id, body.edited_text))

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from domain.turns.reader import list_turn_generations
from domain.turns.writer import delete_message, delete_messages, edit_generation, edit_user_message, prepare_chat_stream, prepare_regenerate_stream, select_generation
from domain.turns.streaming import stream_response
from server.dependencies import DbConn
from server.specs import BulkDeleteMessagesRequest, BulkDeleteMessagesResponse, ChatRequest, EditGenerationRequest, EditMessageRequest, EditMessageResponse, EditResponse, MessageDeleteResponse, RegenerateRequest, SelectResponse, TurnGenerationsResponse


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


@router.get("/api/turns/{turn_id}/generations", response_model=TurnGenerationsResponse)
def get_turn_generations(turn_id: str, conn: DbConn):
    return list_turn_generations(conn, turn_id)


@router.post("/api/generations/{generation_id}/select", response_model=SelectResponse)
def post_select(generation_id: str, conn: DbConn):
    return select_generation(conn, generation_id)


@router.post("/api/generations/{generation_id}/edit", response_model=EditResponse)
def post_edit(generation_id: str, body: EditGenerationRequest, conn: DbConn):
    return edit_generation(conn, generation_id, body.edited_text)


@router.post("/api/messages/{message_id}/edit", response_model=EditMessageResponse)
def post_edit_message(message_id: str, body: EditMessageRequest, conn: DbConn):
    return edit_user_message(conn, message_id, body.edited_text)


@router.delete("/api/messages/{message_id}", response_model=MessageDeleteResponse)
def delete_message_route(message_id: str, conn: DbConn):
    return delete_message(conn, message_id)


@router.post("/api/messages/batch-delete", response_model=BulkDeleteMessagesResponse)
def post_batch_delete_messages(body: BulkDeleteMessagesRequest, conn: DbConn):
    return delete_messages(conn, body.message_ids)

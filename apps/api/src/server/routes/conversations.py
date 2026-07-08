from fastapi import APIRouter

from domain.conversations.reader import get_conversation, get_conversation_settings, list_messages
from domain.conversations.writer import create_conversation, save_conversation_settings
from server.dependencies import DbConn
from server.specs import (
    ConversationDetailResponse,
    ConversationResponse,
    ConversationSettingsResponse,
    CreateConversationRequest,
    GenerationParamsRequest,
    MessagesPageResponse,
)


router = APIRouter()


@router.post("/api/conversations", response_model=ConversationResponse)
def post_conversation(body: CreateConversationRequest, conn: DbConn):
    return create_conversation(conn, body.plot_id, body.title)


@router.get("/api/conversations/{conversation_id}", response_model=ConversationDetailResponse)
def get_conversation_route(conversation_id: str, conn: DbConn):
    return get_conversation(conn, conversation_id)


@router.get("/api/conversations/{conversation_id}/messages", response_model=MessagesPageResponse)
def get_conversation_messages(conversation_id: str, conn: DbConn, before: int | None = None, limit: int = 100):
    return list_messages(conn, conversation_id, before, limit)


@router.get("/api/conversations/{conversation_id}/settings", response_model=ConversationSettingsResponse | None)
def get_settings(conversation_id: str, conn: DbConn):
    return get_conversation_settings(conn, conversation_id)


@router.put("/api/conversations/{conversation_id}/settings", response_model=ConversationSettingsResponse | None)
def put_settings(conversation_id: str, body: GenerationParamsRequest, conn: DbConn):
    return save_conversation_settings(conn, conversation_id, body.to_params())

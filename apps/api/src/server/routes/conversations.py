from fastapi import APIRouter

from domain.conversations.reader import get_conversation, get_conversation_settings, list_conversations, list_messages
from domain.conversations.writer import create_conversation, delete_conversation, update_conversation_settings, update_conversation_title, update_conversation_user_profile
from server.dependencies import DbConn
from server.specs import (
    ConversationDeleteResponse,
    ConversationDetailResponse,
    ConversationResponse,
    ConversationSettingsResponse,
    ConversationsPageResponse,
    CreateConversationRequest,
    GenerationParamsRequest,
    MessagesPageResponse,
    SetConversationTitleRequest,
    SetConversationUserProfileRequest,
)


router = APIRouter()


@router.post("/api/conversations", response_model=ConversationResponse)
def post_conversation(body: CreateConversationRequest, conn: DbConn):
    return create_conversation(conn, body.plot_id, body.user_profile_id, body.title)


@router.get("/api/conversations", response_model=ConversationsPageResponse)
def list_conversations_route(conn: DbConn, before: int | None = None, limit: int = 100):
    return list_conversations(conn, before, limit)


@router.get("/api/conversations/{conversation_id}", response_model=ConversationDetailResponse)
def get_conversation_route(conversation_id: str, conn: DbConn):
    return get_conversation(conn, conversation_id)


@router.delete("/api/conversations/{conversation_id}", response_model=ConversationDeleteResponse)
def delete_conversation_route(conversation_id: str, conn: DbConn):
    return delete_conversation(conn, conversation_id)


@router.get("/api/conversations/{conversation_id}/messages", response_model=MessagesPageResponse)
def get_conversation_messages(conversation_id: str, conn: DbConn, before: int | None = None, limit: int = 100):
    return list_messages(conn, conversation_id, before, limit)


@router.put("/api/conversations/{conversation_id}/user-profile", response_model=ConversationDetailResponse)
def put_conversation_user_profile(conversation_id: str, body: SetConversationUserProfileRequest, conn: DbConn):
    return update_conversation_user_profile(conn, conversation_id, body.user_profile_id)


@router.put("/api/conversations/{conversation_id}/title", response_model=ConversationDetailResponse)
def put_conversation_title(conversation_id: str, body: SetConversationTitleRequest, conn: DbConn):
    return update_conversation_title(conn, conversation_id, body.title)


@router.get("/api/conversations/{conversation_id}/settings", response_model=ConversationSettingsResponse | None)
def get_settings(conversation_id: str, conn: DbConn):
    return get_conversation_settings(conn, conversation_id)


@router.put("/api/conversations/{conversation_id}/settings", response_model=ConversationSettingsResponse | None)
def put_settings(conversation_id: str, body: GenerationParamsRequest, conn: DbConn):
    return update_conversation_settings(conn, conversation_id, body.to_params())

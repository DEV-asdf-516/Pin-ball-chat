from fastapi import APIRouter

from domain.conversations.reader import get_conversation, get_conversation_settings, list_conversations, list_messages
from domain.conversations.writer import create_conversation, delete_conversation, update_conversation_settings, update_conversation_title, update_conversation_user_profile
from domain.conversations.importer.importer import commit_import_session, discard_import_session, get_import_session, upload_import_part, start_import_session
from core.errors import NotFound
from server.dependencies import DbConn
from server.specs import (
    CommitImportSessionResponse,
    ConversationDeleteResponse,
    ConversationDetailResponse,
    ConversationResponse,
    ConversationSettingsResponse,
    ConversationsPageResponse,
    CreateConversationRequest,
    DiscardImportSessionResponse,
    GenerationParamsRequest,
    ImportSessionResponse,
    MessagesPageResponse,
    SetConversationTitleRequest,
    SetConversationUserProfileRequest,
    StartImportSessionRequest,
    UploadImportPartRequest,
    UploadImportPartResponse,
)


router = APIRouter()

def _matching_import_session(conversation_id: str, session_id: str) -> dict:
    session = get_import_session(conversation_id)
    if session is None or session["sessionId"] != session_id:
        raise NotFound("import session not found")
    return session

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


@router.get("/api/conversations/{conversation_id}/session", response_model=ImportSessionResponse)
def get_import_session_route(conversation_id: str):
    session = get_import_session(conversation_id)
    if session is None:
        raise NotFound("import session not found")
    return session


@router.post("/api/conversations/{conversation_id}/sessions", response_model=ImportSessionResponse)
def post_import_session(conversation_id: str, body: StartImportSessionRequest, conn: DbConn):
    return start_import_session(conn, conversation_id, body.to_dict())


@router.put("/api/conversations/{conversation_id}/sessions/{session_id}/parts/{part_number}", response_model=UploadImportPartResponse)
def put_import_session_part(conversation_id: str, session_id: str, part_number: int, body: UploadImportPartRequest):
    _matching_import_session(conversation_id, session_id)
    return upload_import_part(session_id, part_number, body.to_dict())


@router.post("/api/conversations/{conversation_id}/sessions/{session_id}/commit", response_model=CommitImportSessionResponse)
def post_import_session_commit(conversation_id: str, session_id: str, conn: DbConn):
    _matching_import_session(conversation_id, session_id)
    return commit_import_session(conn, session_id)


@router.delete("/api/conversations/{conversation_id}/sessions/{session_id}", response_model=DiscardImportSessionResponse)
def delete_import_session(conversation_id: str, session_id: str):
    _matching_import_session(conversation_id, session_id)
    return discard_import_session(session_id)

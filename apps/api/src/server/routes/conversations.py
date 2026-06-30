from fastapi import APIRouter

from domain.services import create_conversation
from server.routes._helpers import db_business, one
from server.schemas import ConversationResponse, CreateConversationRequest


router = APIRouter()


@router.post("/api/conversations", response_model=ConversationResponse)
def post_conversation(body: CreateConversationRequest):
    return db_business(lambda conn: create_conversation(conn, body.plot_id, body.title))


@router.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: str):
    return one("conversations", conversation_id)

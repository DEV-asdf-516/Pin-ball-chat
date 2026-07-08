import sqlite3

from core.db import CursorQuery, cursor, exists, find_one
from core.errors import ensure, get_or_raise
from domain.conversations.specs import CONVERSATION_SETTINGS, CONVERSATIONS
from domain.turns.specs import MESSAGES


def get_conversation(conn: sqlite3.Connection, conversation_id: str) -> dict:
    row: dict | None = find_one(conn, CONVERSATIONS, conversation_id)
    return get_or_raise(row, "conversation not found")


def list_messages(conn: sqlite3.Connection, conversation_id: str, before: int | None = None, limit: int = 100) -> dict:
    conversation_found: bool = exists(conn, CONVERSATIONS, "id", conversation_id)
    ensure(conversation_found, "conversation not found")

    query : CursorQuery = CursorQuery(
        filter_column="conversation_id", 
        filter_value=conversation_id, 
        before=before, 
        limit=limit
    )
    page: dict = cursor(conn, MESSAGES, query)
    
    return {
        "messages": page["items"],
        "nextCursor": page["nextCursor"],
        "hasMore": page["hasMore"]
    }


def get_conversation_settings(conn: sqlite3.Connection, conversation_id: str) -> dict | None:
    conversation_found: bool = exists(conn, CONVERSATIONS, "id", conversation_id)
    ensure(conversation_found, "conversation not found")

    settings: dict | None = find_one(conn, CONVERSATION_SETTINGS, conversation_id)
    
    if not settings:
        return None
    
    settings["compact_prompt"] = bool(settings["compact_prompt"]) if settings["compact_prompt"] is not None else None
    
    return settings

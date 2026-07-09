import sqlite3

from core.db import exists, fetch_all, find_one
from core.errors import ensure, get_or_raise
from domain.conversations.specs import CONVERSATION_SETTINGS, CONVERSATIONS


def get_conversation(conn: sqlite3.Connection, conversation_id: str) -> dict:
    row: dict | None = find_one(conn, CONVERSATIONS, conversation_id)
    return get_or_raise(row, "conversation not found")


def list_messages(conn: sqlite3.Connection, conversation_id: str, before: int | None = None, limit: int = 100) -> dict:
    """rejected(재생성으로 밀려난) assistant 메시지는 유저에게 노출하지 않는다 — 최종 승인된 응답만 보여준다."""
    conversation_found: bool = exists(conn, CONVERSATIONS, "id", conversation_id)
    ensure(conversation_found, "conversation not found")

    limit = max(1, min(limit, 200))
    cursor_clause: str = "AND m.rowid<?" if before is not None else ""
    params: tuple = (conversation_id, *((before,) if before is not None else ()), limit)

    rows_desc: list[sqlite3.Row] = fetch_all(
        conn,
        f"""
        SELECT m.rowid, m.id, m.conversation_id, m.role, m.content, m.turn_id, m.generation_id, m.created_at
        FROM messages m
        LEFT JOIN generations g ON m.generation_id = g.id
        WHERE m.conversation_id=? AND (m.generation_id IS NULL OR g.rejected=0) {cursor_clause}
        ORDER BY m.rowid DESC
        LIMIT ?
        """,
        params,
    )
    items: list[dict] = [dict(r) for r in rows_desc]
    has_more: bool = False

    if items:
        oldest_rowid: int = items[-1]["rowid"]
        has_more = bool(fetch_all(
            conn,
            """
            SELECT 1
            FROM messages m
            LEFT JOIN generations g ON m.generation_id = g.id
            WHERE m.conversation_id=? AND (m.generation_id IS NULL OR g.rejected=0) AND m.rowid<?
            LIMIT 1
            """,
            (conversation_id, oldest_rowid),
        ))

    next_cursor: str | None = str(items[-1]["rowid"]) if has_more else None
    for item in items:
        item.pop("rowid")
    items.reverse()

    return {
        "messages": items,
        "nextCursor": next_cursor,
        "hasMore": has_more,
    }


def get_conversation_settings(conn: sqlite3.Connection, conversation_id: str) -> dict | None:
    conversation_found: bool = exists(conn, CONVERSATIONS, "id", conversation_id)
    ensure(conversation_found, "conversation not found")

    settings: dict | None = find_one(conn, CONVERSATION_SETTINGS, conversation_id)
    
    if not settings:
        return None
    
    settings["compact_prompt"] = bool(settings["compact_prompt"]) if settings["compact_prompt"] is not None else None
    
    return settings

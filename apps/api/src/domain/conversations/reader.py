import sqlite3

from core.db import exists, fetch_all, fetch_one, find_by_id, select_cols
from core.errors import NotFound


def get_conversation(conn: sqlite3.Connection, conversation_id: str) -> dict:
    row: dict | None = find_by_id(conn, "conversations", conversation_id)
    if not row:
        raise NotFound("conversation not found")
    return row


def list_messages(conn: sqlite3.Connection, conversation_id: str, before: int | None = None, limit: int = 100) -> dict:
    if not exists(conn, "conversations", "id", conversation_id):
        raise NotFound("conversation not found")
    limit = max(1, min(limit, 200))
    cols: str = select_cols("messages")
    if before is not None:
        rows_desc: list[sqlite3.Row] = fetch_all(
            conn,
            f"SELECT rowid, {cols} FROM messages WHERE conversation_id=? AND rowid<? ORDER BY rowid DESC LIMIT ?",
            (conversation_id, before, limit),
        )
    else:
        rows_desc: list[sqlite3.Row] = fetch_all(
            conn,
            f"SELECT rowid, {cols} FROM messages WHERE conversation_id=? ORDER BY rowid DESC LIMIT ?",
            (conversation_id, limit),
        )
    items: list[dict] = [dict(r) for r in rows_desc]
    has_more: bool = False
    if items:
        oldest_rowid: int = items[-1]["rowid"]
        has_more = bool(fetch_one(
            conn,
            "SELECT 1 FROM messages WHERE conversation_id=? AND rowid<? LIMIT 1",
            (conversation_id, oldest_rowid),
        ))
    next_cursor: str | None = str(items[-1]["rowid"]) if has_more else None
    for item in items:
        item.pop("rowid")
    items.reverse()
    return {"messages": items, "nextCursor": next_cursor, "hasMore": has_more}


def get_conversation_settings(conn: sqlite3.Connection, conversation_id: str) -> dict | None:
    if not exists(conn, "conversations", "id", conversation_id):
        raise NotFound("conversation not found")
    row: sqlite3.Row | None = fetch_one(
        conn,
        f"SELECT {select_cols('conversation_settings')} FROM conversation_settings WHERE conversation_id=?",
        (conversation_id,),
    )
    if not row:
        return None
    settings: dict = dict(row)
    settings["compact_prompt"] = bool(settings["compact_prompt"]) if settings["compact_prompt"] is not None else None
    return settings

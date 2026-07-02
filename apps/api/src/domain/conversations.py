import sqlite3

from core.db import exists, fetch_all, fetch_one, find_by_id, new_id, select_cols
from core.errors import NotFound
from domain.content.reader import content_exists, find_content_by_id
from domain.content.specs import ContentKind
from domain.generation_params import GenerationParams
from util.time_util import utc_now_string


def create_conversation(conn: sqlite3.Connection, plot_id: str, title: str | None = None) -> dict:
    plot: dict | None = find_content_by_id(conn, ContentKind.PLOT, plot_id)
    if not plot:
        raise NotFound("plot not found")
    if not content_exists(conn, ContentKind.CHARACTER, plot["character_id"]):
        raise NotFound("plot character missing")
    if not content_exists(conn, ContentKind.USER_PROFILE, plot["user_profile_id"]):
        raise NotFound("plot user_profile missing")
    
    conv_id, ts = new_id("conv"), utc_now_string()
    
    conn.execute("INSERT INTO conversations VALUES (?,?,?,?,?,?)", (conv_id, plot_id, title, None, ts, ts))
    
    return {"conversationId": conv_id, "plotId": plot_id}


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


def save_conversation_settings(conn: sqlite3.Connection, conversation_id: str, params: GenerationParams) -> dict | None:
    if not exists(conn, "conversations", "id", conversation_id):
        raise NotFound("conversation not found")
    ts: str = utc_now_string()
    conn.execute(
        """
        INSERT INTO conversation_settings
        (conversation_id,provider,model,num_predict,num_ctx,compact_prompt,adapter_id,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT(conversation_id) DO UPDATE SET
          provider=excluded.provider,
          model=excluded.model,
          num_predict=excluded.num_predict,
          num_ctx=excluded.num_ctx,
          compact_prompt=excluded.compact_prompt,
          adapter_id=excluded.adapter_id,
          updated_at=excluded.updated_at
        """,
        (conversation_id, params.provider_name, params.model, params.num_predict, params.num_ctx, int(params.compact_prompt), params.adapter_id, ts, ts),
    )
    return get_conversation_settings(conn, conversation_id)

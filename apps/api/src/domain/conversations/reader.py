import sqlite3

from core.db import CursorClause, CursorQuery, RawSQL, ReadQuery, exists, find_one, paginate
from core.errors import ensure, get_or_raise
from domain.conversations.specs import CONVERSATION_SETTINGS, CONVERSATIONS
from util.string_util import join_columns


def active_messages_sql(columns: tuple[str, ...], order: str = "DESC", extra_where: str = "", tail: str = "") -> str:
    # 재생성으로 rejected된 assistant 후보를 뺀, generations.rejected=0인 "active" 메시지 조회 쿼리를 조립한다.
    # list_messages/build_prompt의 recent/writer의 _active_messages가 컬럼·정렬 방향·커서 조건만 다르게 넣어 공유한다.
    return f"""
    SELECT {join_columns(columns)}
    FROM messages m
    LEFT JOIN generations g
    ON m.generation_id = g.id
    WHERE m.conversation_id=:conversation_id
    AND (m.generation_id IS NULL OR g.rejected=0)
    {extra_where}
    ORDER BY m.rowid {order}
    {tail}
    """


def get_conversation(conn: sqlite3.Connection, conversation_id: str) -> dict:
    row: dict | None = find_one(conn, ReadQuery.by_id(CONVERSATIONS, conversation_id))
    return get_or_raise(row, "conversation not found")


def list_conversations(conn: sqlite3.Connection, before: int | None = None, limit: int = 100) -> dict:
    limit = max(1, min(limit, 200))
    params: dict = {"before": before} if before is not None else {}

    cursor_query = CursorQuery(
        query=RawSQL(f"""
        SELECT
            rowid,
            id,
            plot_id,
            user_profile_id,
            title,
            active_adapter_id,
            created_at,
            updated_at
        FROM conversations
        {CursorQuery.clause("rowid", before)}
        ORDER BY rowid DESC
        LIMIT :limit
        """),
        params=params,
        limit=limit,
    )
    page: dict = paginate(conn, cursor_query)

    return {
        "conversations": page["items"],
        "nextCursor": page["nextCursor"],
        "hasMore": page["hasMore"],
    }


def list_messages(conn: sqlite3.Connection, conversation_id: str, before: int | None = None, limit: int = 100) -> dict:
    conversation_found: bool = exists(conn, ReadQuery.by_id(CONVERSATIONS, conversation_id))
    ensure(conversation_found, "conversation not found")

    limit = max(1, min(limit, 200))

    params: dict = {
        "conversation_id": conversation_id, 
        **({"before": before} if before is not None else {})
    }

    cursor_query = CursorQuery(
        query=RawSQL(
            active_messages_sql(
                ("m.rowid", 
                 "m.id", 
                 "m.conversation_id", 
                 "m.role", 
                 "m.content", 
                 "m.turn_id", 
                 "m.generation_id", 
                 "m.created_at"
                 ),
                extra_where=CursorQuery.clause("m.rowid", before, prefix=CursorClause.AND),
                tail="LIMIT :limit",
        )),
        params=params,
        limit=limit,
    )
    page: dict = paginate(conn, cursor_query)
    page["items"].reverse()

    return {
        "messages": page["items"],
        "nextCursor": page["nextCursor"],
        "hasMore": page["hasMore"],
    }


def get_conversation_settings(conn: sqlite3.Connection, conversation_id: str) -> dict | None:
    conversation_found: bool = exists(conn, ReadQuery.by_id(CONVERSATIONS, conversation_id))
    
    ensure(conversation_found, "conversation not found")

    settings: dict | None = find_one(conn, ReadQuery.by_id(CONVERSATION_SETTINGS, conversation_id))
    
    if not settings:
        return None
    
    settings["compact_prompt"] = bool(settings["compact_prompt"]) if settings["compact_prompt"] is not None else None
    
    return settings

import sqlite3

from core.db import CursorClause, CursorQuery, RawSQL, ReadQuery, exists, find_one, paginate
from core.errors import ensure, get_or_raise
from domain.conversations.specs import CONVERSATION_SETTINGS, CONVERSATIONS
from util.string_util import join_columns


def active_messages_sql(columns: tuple[str, ...], order: str = "DESC", extra_where: str = "", tail: str = "") -> str:
    # 재생성으로 rejected된 assistant 후보와, 빈 입력(전개 요청)으로 생성된 내용 없는 user 턴을 뺀
    # "active" 메시지 조회 쿼리를 조립한다. 빈 입력 턴은 turns.user_message_id FK 때문에 messages
    # row 자체는 남지만(요청은 실제로 있었으니까), 대화 이력으로는 취급하지 않는다 — 매 호출 재조립되는
    # build_prompt()의 recent나 요약 대상(pending)에 빈 turn이 그대로 다시 들어가면 의미 없는 히스토리만 남는다.
    # list_messages/build_prompt의 recent/summary writer의 pending이 컬럼·정렬 방향·커서 조건만 다르게 넣어 공유한다.
    return f"""
    SELECT {join_columns(columns)}
    FROM messages m
    LEFT JOIN generations g
    ON m.generation_id = g.id
    WHERE m.conversation_id=:conversation_id
    AND (m.generation_id IS NULL OR g.rejected=0)
    AND (m.role != 'user' OR m.content != '')
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

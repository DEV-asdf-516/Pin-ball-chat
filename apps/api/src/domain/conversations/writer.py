import sqlite3

from core.db import exists, insert, new_id
from core.errors import NotFound
from domain.content.reader import content_exists, find_content_by_id
from domain.content.specs import ContentKind
from domain.conversations.reader import get_conversation_settings
from domain.generation_params import GenerationParams
from util.time_util import utc_now_string

_CONVERSATIONS_COLUMNS = ("id", "plot_id", "title", "active_adapter_id", "created_at", "updated_at")


def create_conversation(conn: sqlite3.Connection, plot_id: str, title: str | None = None) -> dict:
    plot: dict | None = find_content_by_id(conn, ContentKind.PLOT, plot_id)
    if not plot:
        raise NotFound("plot not found")
    if not content_exists(conn, ContentKind.CHARACTER, plot["character_id"]):
        raise NotFound("plot character missing")
    if not content_exists(conn, ContentKind.USER_PROFILE, plot["user_profile_id"]):
        raise NotFound("plot user_profile missing")

    conv_id, ts = new_id("conv"), utc_now_string()
    insert(conn, "conversations", _CONVERSATIONS_COLUMNS, (conv_id, plot_id, title, None, ts, ts))

    return {"conversationId": conv_id, "plotId": plot_id}


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

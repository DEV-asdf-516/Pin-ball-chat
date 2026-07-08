import sqlite3

from core.db import exists, insert, new_id, upsert
from core.errors import ensure
from domain.catalog.reader import find_catalog_by_id
from domain.catalog.specs import CatalogKind
from domain.conversations.reader import get_conversation_settings
from domain.conversations.specs import CONVERSATION_SETTINGS, CONVERSATIONS
from domain.specs import GenerationParams
from util.time_util import utc_now_string

# 대화 생성
def create_conversation(conn: sqlite3.Connection, plot_id: str, title: str | None = None) -> dict:
    plot: dict | None = find_catalog_by_id(conn, CatalogKind.PLOT, plot_id)
    ensure(plot, "plot not found")

    conv_id, ts = new_id("conv"), utc_now_string()
    
    insert(conn, CONVERSATIONS, {
        "id": conv_id,
        "plot_id": plot_id,
        "title": title,
        "active_adapter_id": None,
        "created_at": ts,
        "updated_at": ts,
    })

    return {
        "conversationId": conv_id, 
        "plotId": plot_id
        }


def save_conversation_settings(conn: sqlite3.Connection, conversation_id: str, params: GenerationParams) -> dict | None:
    conversation_found: bool = exists(conn, CONVERSATIONS, "id", conversation_id)
    ensure(conversation_found, "conversation not found")
    ts: str = utc_now_string()
    
    upsert(conn, CONVERSATION_SETTINGS, {
        "conversation_id": conversation_id,
        "provider": params.provider_name,
        "model": params.model,
        "num_predict": params.num_predict,
        "num_ctx": params.num_ctx,
        "compact_prompt": int(params.compact_prompt),
        "adapter_id": params.adapter_id,
        "created_at": ts,
        "updated_at": ts,
    })
    
    return get_conversation_settings(conn, conversation_id)

import sqlite3

from core.db import Bind, In, RawSQL, ReadQuery, WriteQuery, delete, exists, insert, new_id, update, upsert
from core.errors import ensure
from domain.catalog.reader import find_catalog_by_id
from domain.catalog.specs import CatalogKind
from domain.conversations.reader import get_conversation, get_conversation_settings
from domain.conversations.specs import CONVERSATION_SETTINGS, CONVERSATIONS
from domain.prompts.context import build_ctx, render_value, resolve_prompt_context, row_json
from domain.specs import GenerationParams
from domain.turns.specs import GENERATION_EDITS, GENERATIONS, MESSAGES, TURNS, USER_ACTIONS
from util.safe_util import get_safe_dict, get_safe_list
from util.time_util import utc_now_string


def _materialize_intro(conn: sqlite3.Connection, conversation_id: str) -> None:
    # 실제 턴이 하나라도 생기면 그 다음부턴 건드리지 않는다 — 과거 assistant 응답 속 이름과 어긋나지 않게.
    # 그 전까지는(프로필을 다시 고르는 경우 포함) upsert로 최신 프로필 이름으로 재렌더한다.
    has_turns: bool = exists(conn, ReadQuery(TURNS, where=Bind({"conversation_id": conversation_id})))
    
    if has_turns:
        return

    _, plot, char, user = resolve_prompt_context(conn, conversation_id)
    
    plot_json: dict = row_json(plot, "plot_json")
    intro: dict = get_safe_dict(plot_json, "intro")
    blocks: list[dict] = get_safe_list(intro, "blocks")
    
    if not blocks:
        return

    ctx: dict = build_ctx(plot, char, user)
    warnings: list = []
    ts: str = utc_now_string()

    for index, block in enumerate(blocks):
        upsert(conn, MESSAGES, Bind({
            "id": f"intro_{conversation_id}_{index}",
            "conversation_id": conversation_id,
            "role": block["type"],
            "content": render_value(block["content"], ctx, warnings),
            "turn_id": None,
            "generation_id": None,
            "created_at": ts,
        }))


# 대화 생성. userProfileId는 나중에(대화방 진입 시 팝업으로) 정할 수 있어 생성 시점엔 optional이다.
def create_conversation(conn: sqlite3.Connection, plot_id: str, user_profile_id: str | None = None, title: str | None = None) -> dict:
    plot: dict | None = find_catalog_by_id(conn, CatalogKind.PLOT, plot_id)
    ensure(plot, "plot not found")

    if user_profile_id is not None:
        user_profile: dict | None = find_catalog_by_id(conn, CatalogKind.USER_PROFILE, user_profile_id)
        ensure(user_profile, "user profile not found")

    conv_id, ts = new_id("conv"), utc_now_string()

    insert(conn, CONVERSATIONS, Bind({
        "id": conv_id,
        "plot_id": plot_id,
        "user_profile_id": user_profile_id,
        "title": title,
        "active_adapter_id": None,
        "summary_text": None,
        "summary_through_rowid": 0,
        "created_at": ts,
        "updated_at": ts,
    }))

    if user_profile_id is not None:
        _materialize_intro(conn, conv_id)

    return {
        "conversationId": conv_id,
        "plotId": plot_id,
        "userProfileId": user_profile_id,
    }


def update_conversation_user_profile(conn: sqlite3.Connection, conversation_id: str, user_profile_id: str) -> dict:
    conversation_found: bool = exists(conn, ReadQuery.by_id(CONVERSATIONS, conversation_id))
    ensure(conversation_found, "conversation not found")

    user_profile: dict | None = find_catalog_by_id(conn, CatalogKind.USER_PROFILE, user_profile_id)
    ensure(user_profile, "user profile not found")

    update(conn, WriteQuery(
        CONVERSATIONS,
        Bind({"user_profile_id": user_profile_id, "updated_at": utc_now_string()}),
        Bind({"id": conversation_id}),
    ))

    _materialize_intro(conn, conversation_id)

    return get_conversation(conn, conversation_id)


def update_conversation_title(conn: sqlite3.Connection, conversation_id: str, title: str | None) -> dict:
    conversation_found: bool = exists(conn, ReadQuery.by_id(CONVERSATIONS, conversation_id))
    ensure(conversation_found, "conversation not found")

    update(conn, WriteQuery(
        CONVERSATIONS,
        Bind({"title": title, "updated_at": utc_now_string()}),
        Bind({"id": conversation_id}),
    ))

    return get_conversation(conn, conversation_id)


def update_conversation_settings(conn: sqlite3.Connection, conversation_id: str, params: GenerationParams) -> dict | None:
    conversation_found: bool = exists(conn, ReadQuery.by_id(CONVERSATIONS, conversation_id))
    ensure(conversation_found, "conversation not found")
    ts: str = utc_now_string()
    
    upsert(conn, CONVERSATION_SETTINGS, Bind({
        "conversation_id": conversation_id,
        "provider": params.provider_name,
        "model": params.model,
        "num_predict": params.num_predict,
        "num_ctx": params.num_ctx,
        "compact_prompt": int(params.compact_prompt),
        "adapter_id": params.adapter_id,
        "created_at": ts,
        "updated_at": ts,
    }))
    
    return get_conversation_settings(conn, conversation_id)


def delete_conversation(conn: sqlite3.Connection, conversation_id: str) -> dict:
    conversation_found: bool = exists(conn, ReadQuery.by_id(CONVERSATIONS, conversation_id))
    ensure(conversation_found, "conversation not found")

    delete(conn, WriteQuery(GENERATION_EDITS, where=Bind({
        "generation_id": In(
            RawSQL(f"SELECT id FROM {GENERATIONS.table} WHERE conversation_id=:conversation_id"),
            params=Bind({"conversation_id": conversation_id}),
        )
    })))
    delete(conn, WriteQuery(USER_ACTIONS, where=Bind({"conversation_id": conversation_id})))
    delete(conn, WriteQuery(GENERATIONS, where=Bind({"conversation_id": conversation_id})))
    delete(conn, WriteQuery(TURNS, where=Bind({"conversation_id": conversation_id})))
    delete(conn, WriteQuery(MESSAGES, where=Bind({"conversation_id": conversation_id})))
    delete(conn, WriteQuery.by_id(CONVERSATION_SETTINGS, conversation_id))
    delete(conn, WriteQuery.by_id(CONVERSATIONS, conversation_id))

    return {"conversationId": conversation_id, "deleted": True}

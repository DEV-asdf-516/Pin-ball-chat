import hashlib
import json
import sqlite3
from dataclasses import dataclass

from ai.registry import runtime_params
from ai.specs import GenerateRequest
from core.db import Bind, In, Ne, ReadQuery, RawSQL, WriteQuery, delete, fetch_one, find_all, find_one, insert, new_id, select_cols, update
from core.errors import ensure, get_or_raise
from domain.prompts.reader import BuiltPrompt, build_prompt, snapshot_text
from domain.specs import GenerationParams
from domain.turns.specs import GENERATION_EDITS, GENERATIONS, MESSAGES, TURNS, USER_ACTIONS, ActionType, PreparedGeneration
from util.time_util import utc_now_string


def _next_candidate_index(conn: sqlite3.Connection, turn_id: str) -> int:
    return fetch_one(
        conn,
        RawSQL("""
        SELECT COUNT(*) n
        FROM generations
        WHERE turn_id=:turn_id
        """),
        {"turn_id": turn_id},
    )["n"]


@dataclass
class _UserAction:
    conversation_id: str
    turn_id: str | None
    generation_id: str | None
    action_type: ActionType


def _record_user_action(conn: sqlite3.Connection, action: _UserAction) -> None:
    insert(conn, USER_ACTIONS, Bind({
        "id": new_id("act"),
        "conversation_id": action.conversation_id,
        "turn_id": action.turn_id,
        "generation_id": action.generation_id,
        "action_type": action.action_type,
        "payload_json": None,
        "created_at": utc_now_string(),
    }))


def save_generation_output(
    conn: sqlite3.Connection,
    prepared: PreparedGeneration,
    params: GenerationParams,
    req: GenerateRequest,
    output: str,
) -> dict:
    built: BuiltPrompt = prepared.built
    candidate_index: int = _next_candidate_index(conn, prepared.turn_id)
    gen_id: str = new_id("gen")
    msg_id: str = new_id("msg")
    ts: str = utc_now_string()
    snapshot: str = snapshot_text(built.system, built.messages)
    stored_params: dict = {
        "warnings": built.warnings,
        "compactPrompt": params.compact_prompt,
        **runtime_params(req, params.provider_name),
    }

    insert(conn, GENERATIONS, Bind({
        "id": gen_id,
        "turn_id": prepared.turn_id,
        "conversation_id": prepared.conversation_id,
        "plot_id": built.plot["id"],
        "character_id": built.char["id"],
        "user_profile_id": built.user["id"],
        "model_id": params.model,
        "adapter_id": params.adapter_id,
        "candidate_index": candidate_index,
        "prompt_snapshot": snapshot,
        "prompt_hash": hashlib.sha256(snapshot.encode()).hexdigest(),
        "output_text": output,
        "params_json": json.dumps(stored_params, ensure_ascii=False),
        "output_token_count": len(output.split()),
        "created_at": ts,
    }))

    insert(conn, MESSAGES, Bind({
        "id": msg_id,
        "conversation_id": prepared.conversation_id,
        "role": "assistant",
        "content": output,
        "turn_id": prepared.turn_id,
        "generation_id": gen_id,
        "created_at": ts,
    }))

    action = _UserAction(prepared.conversation_id, prepared.turn_id, gen_id, prepared.action_type)
    _record_user_action(conn, action)
    
    return {
        "generationId": gen_id,
        "messageId": msg_id,
        "candidateIndex": candidate_index
        }


def insert_user_turn(conn: sqlite3.Connection, prepared: PreparedGeneration) -> None:
    insert(conn, MESSAGES, Bind({
        "id": prepared.message_id,
        "conversation_id": prepared.conversation_id,
        "role": "user",
        "content": prepared.user_message,
        "turn_id": prepared.turn_id,
        "generation_id": None,
        "created_at": prepared.created_at,
    }))
    insert(conn, TURNS, Bind({
        "id": prepared.turn_id,
        "conversation_id": prepared.conversation_id,
        "user_message_id": prepared.message_id,
        "selected_generation_id": None,
        "regenerate_count": 0,
        "status": "open",
        "created_at": prepared.created_at,
        "updated_at": prepared.created_at,
    }))


def start_regeneration(conn: sqlite3.Connection, prepared: PreparedGeneration) -> None:
    if prepared.current_generation_id:
        update(conn, WriteQuery(GENERATIONS, Bind({"rejected": 1}), Bind({"id": prepared.current_generation_id})))

    update(conn, WriteQuery(TURNS,
        Bind({
         "regenerate_count": RawSQL("regenerate_count+1"),
         "updated_at": utc_now_string()
        }),
        Bind({"id": prepared.turn_id})
    ))

    action = _UserAction(prepared.conversation_id, prepared.turn_id, prepared.current_generation_id, ActionType.GENERATION_REGENERATED)
    
    _record_user_action(conn, action)


def prepare_chat_stream(conn: sqlite3.Connection, conversation_id: str, message: str) -> PreparedGeneration:
    ts: str = utc_now_string()
    msg_id: str = new_id("msg")
    turn_id: str = new_id("turn")
    
    built: BuiltPrompt = build_prompt(conn, conversation_id, message)
    
    return PreparedGeneration(
        conversation_id=conversation_id,
        turn_id=turn_id,
        message_id=msg_id,
        created_at=ts,
        user_message=message,
        built=built,
        action_type=ActionType.GENERATION_SHOWN,
    )


def prepare_regenerate_stream(conn: sqlite3.Connection, turn_id: str) -> PreparedGeneration:
    turn_row: dict | None = find_one(conn, ReadQuery.by_id(TURNS, turn_id))
    turn: dict = get_or_raise(turn_row, "turn not found")

    # 유저가 </>로 이전 후보를 다시 선택해뒀을 수 있어서, "가장 최근 candidate"가 아니라
    # 실제로 selected_generation_id로 표시된 generation을 reject 대상으로 삼는다.
    # 아직 아무것도 select한 적 없으면(=None) candidate_index가 가장 큰 것으로 대체한다.
    current_generation_id: str | None = turn["selected_generation_id"]
    if current_generation_id is None:
        current: sqlite3.Row | None = fetch_one(
            conn,
            RawSQL(f"""
            SELECT {select_cols('generations')}
            FROM generations
            WHERE turn_id=:turn_id
            ORDER BY candidate_index DESC
            LIMIT 1
            """),
            {"turn_id": turn_id},
        )
        current_generation_id = current["id"] if current else None

    user_message: str = find_one(conn, ReadQuery.by_id(MESSAGES, turn["user_message_id"]))["content"]
    built: BuiltPrompt = build_prompt(conn, turn["conversation_id"], user_message)

    return PreparedGeneration(
        conversation_id=turn["conversation_id"],
        turn_id=turn_id,
        current_generation_id=current_generation_id,
        user_message=user_message,
        built=built,
        action_type=ActionType.GENERATION_REGENERATED,
    )


def select_generation(conn: sqlite3.Connection, generation_id: str) -> dict:
    gen_row: dict | None = find_one(conn, ReadQuery.by_id(GENERATIONS, generation_id))
    gen: dict = get_or_raise(gen_row, "generation not found")

    update(conn, WriteQuery(TURNS,
           Bind({
               "selected_generation_id": generation_id,
                "updated_at": utc_now_string()
           }),
           Bind({"id": gen["turn_id"]})))
    update(conn, WriteQuery(GENERATIONS, Bind({"selected": 0}), Bind({"turn_id": gen["turn_id"]})))
    update(conn, WriteQuery(GENERATIONS, Bind({"rejected": 1}), Bind({"turn_id": gen["turn_id"], "id": Ne(generation_id)})))
    update(conn, WriteQuery(GENERATIONS, Bind({"selected": 1, "rejected": 0}), Bind({"id": generation_id})))
    
    action = _UserAction(gen["conversation_id"], gen["turn_id"], generation_id, ActionType.GENERATION_SELECTED)
    _record_user_action(conn, action)
    
    return {
        "generationId": generation_id, 
        "selected": True
        }


def edit_generation(conn: sqlite3.Connection, generation_id: str, edited_text: str) -> dict:
    gen_row: dict | None = find_one(conn, ReadQuery.by_id(GENERATIONS, generation_id))
    gen: dict = get_or_raise(gen_row, "generation not found")

    insert(conn, GENERATION_EDITS, Bind({
        "id": new_id("edit"),
        "generation_id": generation_id,
        "original_text": gen["output_text"],
        "edited_text": edited_text,
        "created_at": utc_now_string(),
    }))

    action = _UserAction(gen["conversation_id"], gen["turn_id"], generation_id, ActionType.GENERATION_EDITED)
    _record_user_action(conn, action)
    update(conn, WriteQuery(MESSAGES, Bind({"content": edited_text}), Bind({"generation_id": generation_id})))

    return {
        "generationId": generation_id,
        "edited": True
        }


def edit_user_message(conn: sqlite3.Connection, message_id: str, edited_text: str) -> dict:
    msg_row: dict | None = find_one(conn, ReadQuery.by_id(MESSAGES, message_id))
    msg: dict = get_or_raise(msg_row, "message not found")
    ensure(msg["role"] == "user", "only user messages can be edited here")

    update(conn, WriteQuery(MESSAGES, Bind({"content": edited_text}), Bind({"id": message_id})))

    return {
        "messageId": message_id,
        "edited": True
        }


def delete_messages(conn: sqlite3.Connection, message_ids: list[str]) -> dict:
    rows: list[dict] = find_all(conn, ReadQuery(MESSAGES, where=Bind({"id": In(message_ids)}))) if message_ids else []
    found_ids: set = {r["id"] for r in rows}
    missing: list[str] = [mid for mid in message_ids if mid not in found_ids]
    ensure(not missing, f"message(s) not found: {', '.join(missing)}")

    user_turn_ids: list[str] = sorted({r["turn_id"] for r in rows if r["role"] == "user"})
    assistant_turn_ids: list[str] = sorted({r["turn_id"] for r in rows if r["role"] == "assistant"})
    all_turn_ids: list[str] = sorted(set(user_turn_ids) | set(assistant_turn_ids))

    if all_turn_ids:
        gen_rows: list[dict] = find_all(conn, ReadQuery(GENERATIONS, where=Bind({"turn_id": In(all_turn_ids)})))
        gen_ids: list[str] = [g["id"] for g in gen_rows]
        if gen_ids:
            delete(conn, WriteQuery(GENERATION_EDITS, where=Bind({"generation_id": In(gen_ids)})))
        delete(conn, WriteQuery(GENERATIONS, where=Bind({"turn_id": In(all_turn_ids)})))

    if user_turn_ids:
        # turns.user_message_id가 messages.id를 참조하므로 turns를 messages보다 먼저 지워야 한다.
        delete(conn, WriteQuery(USER_ACTIONS, where=Bind({"turn_id": In(user_turn_ids)})))
        delete(conn, WriteQuery(TURNS, where=Bind({"id": In(user_turn_ids)})))
        delete(conn, WriteQuery(MESSAGES, where=Bind({"turn_id": In(user_turn_ids)})))

    if assistant_turn_ids:
        # 프론트에서 candidate들은 </>로 넘겨보는 메시지 하나로 보이므로, 지우면 후보 전체가 사라져야 한다.
        delete(conn, WriteQuery(MESSAGES, where=Bind({"turn_id": In(assistant_turn_ids), "role": "assistant"})))
        update(conn, WriteQuery(TURNS, Bind({"selected_generation_id": None}), Bind({"id": In(assistant_turn_ids)})))

    return {"messageIds": sorted(found_ids), "turnIds": all_turn_ids, "deleted": True}


def delete_message(conn: sqlite3.Connection, message_id: str) -> dict:
    result: dict = delete_messages(conn, [message_id])
    turn_id: str | None = result["turnIds"][0] if result["turnIds"] else None
    return {"messageId": message_id, "turnId": turn_id, "deleted": True}

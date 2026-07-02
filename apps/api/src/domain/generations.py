import hashlib
import json
import sqlite3

from ai.registry import generate_text, runtime_params
from util.time_util import utc_now_string
from core.db import fetch_one, find_by_id, new_id, select_cols
from core.errors import NotFound
from domain.generation_params import GenerationParams
from domain.prompts import BuiltPrompt, build_prompt


def save_generation_output(
    conn: sqlite3.Connection,
    turn_id: str,
    conversation_id: str,
    built: BuiltPrompt,
    params: GenerationParams,
    output: str,
    action_type: str,
    provider_meta: dict | None = None,
    stream: bool = False,
) -> dict:
    candidate_index: int = fetch_one(conn, "SELECT COUNT(*) n FROM generations WHERE turn_id=?", (turn_id,))["n"]
    gen_id, msg_id, ts = new_id("gen"), new_id("msg"), utc_now_string()
    user_message: str = fetch_one(conn, "SELECT content FROM messages WHERE turn_id=? AND role='user' ORDER BY created_at DESC LIMIT 1", (turn_id,))["content"]
    stored_params: dict = {
        "warnings": built.warnings,
        "compactPrompt": params.compact_prompt,
        **runtime_params(params.provider_name, params.model, built.prompt, user_message, stream, params.num_predict, params.num_ctx),
        **(provider_meta or {}),
    }
    conn.execute(
        """
        INSERT INTO generations
        (id,turn_id,conversation_id,plot_id,character_id,user_profile_id,model_id,adapter_id,candidate_index,prompt_snapshot,prompt_hash,output_text,params_json,output_token_count,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            gen_id,
            turn_id,
            conversation_id,
            built.plot["id"],
            built.char["id"],
            built.user["id"],
            params.model,
            params.adapter_id,
            candidate_index,
            built.prompt,
            hashlib.sha256(built.prompt.encode()).hexdigest(),
            output,
            json.dumps(stored_params, ensure_ascii=False),
            len(output.split()),
            ts,
        ),
    )
    conn.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,?)", (msg_id, conversation_id, "assistant", output, turn_id, gen_id, ts))
    conn.execute("INSERT INTO user_actions VALUES (?,?,?,?,?,?,?)", (new_id("act"), conversation_id, turn_id, gen_id, action_type, None, ts))
    return {"generationId": gen_id, "messageId": msg_id, "candidateIndex": candidate_index}


def insert_user_turn(conn: sqlite3.Connection, conversation_id: str, message: str, msg_id: str, turn_id: str, ts: str) -> None:
    conn.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,?)", (msg_id, conversation_id, "user", message, turn_id, None, ts))
    conn.execute("INSERT INTO turns VALUES (?,?,?,?,?,?,?,?)", (turn_id, conversation_id, msg_id, None, 0, "open", ts, ts))


def mark_regenerated(conn: sqlite3.Connection, conversation_id: str, turn_id: str, current_generation_id: str | None) -> None:
    if current_generation_id:
        conn.execute("UPDATE generations SET rejected=1 WHERE id=?", (current_generation_id,))
    conn.execute("UPDATE turns SET regenerate_count=regenerate_count+1, updated_at=? WHERE id=?", (utc_now_string(), turn_id))
    conn.execute(
        "INSERT INTO user_actions VALUES (?,?,?,?,?,?,?)",
        (new_id("act"), conversation_id, turn_id, current_generation_id, "generation_regenerated", None, utc_now_string()),
    )


def record_generation(conn: sqlite3.Connection, turn_id: str, conversation_id: str, user_message: str, params: GenerationParams) -> dict:
    built: BuiltPrompt = build_prompt(conn, conversation_id, user_message)
    candidate_index: int = fetch_one(conn, "SELECT COUNT(*) n FROM generations WHERE turn_id=?", (turn_id,))["n"]
    output, provider_meta = generate_text(built.prompt, user_message, params.model, candidate_index, params.num_predict, params.num_ctx, params.provider_name)
    saved: dict = save_generation_output(conn, turn_id, conversation_id, built, params, output, "generation_shown", provider_meta)
    return {"generationId": saved["generationId"], "turnId": turn_id, "output": output, "candidateIndex": saved["candidateIndex"]}


def chat(conn: sqlite3.Connection, conversation_id: str, message: str, params: GenerationParams) -> dict:
    ts: str = utc_now_string()
    msg_id, turn_id = new_id("msg"), new_id("turn")
    built: BuiltPrompt = build_prompt(conn, conversation_id, message)
    output, provider_meta = generate_text(built.prompt, message, params.model, 0, params.num_predict, params.num_ctx, params.provider_name)
    insert_user_turn(conn, conversation_id, message, msg_id, turn_id, ts)
    saved: dict = save_generation_output(conn, turn_id, conversation_id, built, params, output, "generation_shown", provider_meta)
    return {"generationId": saved["generationId"], "turnId": turn_id, "output": output, "candidateIndex": saved["candidateIndex"]}


def prepare_chat_stream(conn: sqlite3.Connection, conversation_id: str, message: str) -> dict:
    ts: str = utc_now_string()
    msg_id, turn_id = new_id("msg"), new_id("turn")
    built: BuiltPrompt = build_prompt(conn, conversation_id, message)
    return {
        "conversationId": conversation_id,
        "turnId": turn_id,
        "messageId": msg_id,
        "createdAt": ts,
        "userMessage": message,
        "built": built,
        "actionType": "generation_shown",
    }


def regenerate(conn: sqlite3.Connection, turn_id: str, params: GenerationParams) -> dict:
    turn: dict | None = find_by_id(conn, "turns", turn_id)
    if not turn:
        raise NotFound("turn not found")
    current: sqlite3.Row | None = fetch_one(
        conn,
        f"SELECT {select_cols('generations')} FROM generations WHERE turn_id=? ORDER BY candidate_index DESC LIMIT 1",
        (turn_id,),
    )
    user_msg: str = fetch_one(conn, "SELECT content FROM messages WHERE id=?", (turn["user_message_id"],))["content"]
    built: BuiltPrompt = build_prompt(conn, turn["conversation_id"], user_msg)
    candidate_index: int = fetch_one(conn, "SELECT COUNT(*) n FROM generations WHERE turn_id=?", (turn_id,))["n"]
    output, provider_meta = generate_text(built.prompt, user_msg, params.model, candidate_index, params.num_predict, params.num_ctx, params.provider_name)
    mark_regenerated(conn, turn["conversation_id"], turn_id, current["id"] if current else None)
    saved: dict = save_generation_output(conn, turn_id, turn["conversation_id"], built, params, output, "generation_regenerated", provider_meta)
    return {"generationId": saved["generationId"], "turnId": turn_id, "output": output, "candidateIndex": saved["candidateIndex"]}


def prepare_regenerate_stream(conn: sqlite3.Connection, turn_id: str) -> dict:
    turn: dict | None = find_by_id(conn, "turns", turn_id)
    if not turn:
        raise NotFound("turn not found")
    current: sqlite3.Row | None = fetch_one(
        conn,
        f"SELECT {select_cols('generations')} FROM generations WHERE turn_id=? ORDER BY candidate_index DESC LIMIT 1",
        (turn_id,),
    )
    user_message: str = fetch_one(conn, "SELECT content FROM messages WHERE id=?", (turn["user_message_id"],))["content"]
    built: BuiltPrompt = build_prompt(conn, turn["conversation_id"], user_message)
    return {
        "conversationId": turn["conversation_id"],
        "turnId": turn_id,
        "currentGenerationId": current["id"] if current else None,
        "userMessage": user_message,
        "built": built,
        "actionType": "generation_regenerated",
    }


def select_generation(conn: sqlite3.Connection, generation_id: str) -> dict:
    gen: dict | None = find_by_id(conn, "generations", generation_id)
    if not gen:
        raise NotFound("generation not found")
    conn.execute("UPDATE turns SET selected_generation_id=?, updated_at=? WHERE id=?", (generation_id, utc_now_string(), gen["turn_id"]))
    conn.execute("UPDATE generations SET selected=0 WHERE turn_id=?", (gen["turn_id"],))
    conn.execute("UPDATE generations SET rejected=1 WHERE turn_id=? AND id<>?", (gen["turn_id"], generation_id))
    conn.execute("UPDATE generations SET selected=1,rejected=0 WHERE id=?", (generation_id,))
    conn.execute(
        "INSERT INTO user_actions VALUES (?,?,?,?,?,?,?)",
        (new_id("act"), gen["conversation_id"], gen["turn_id"], generation_id, "generation_selected", None, utc_now_string()),
    )
    return {"generationId": generation_id, "selected": True}


def edit_generation(conn: sqlite3.Connection, generation_id: str, edited_text: str) -> dict:
    gen: dict | None = find_by_id(conn, "generations", generation_id)
    if not gen:
        raise NotFound("generation not found")
    conn.execute(
        "INSERT INTO generation_edits VALUES (?,?,?,?,?)",
        (new_id("edit"), generation_id, gen["output_text"], edited_text, utc_now_string()),
    )
    conn.execute(
        "INSERT INTO user_actions VALUES (?,?,?,?,?,?,?)",
        (new_id("act"), gen["conversation_id"], gen["turn_id"], generation_id, "generation_edited", None, utc_now_string()),
    )
    return {"generationId": generation_id, "edited": True}

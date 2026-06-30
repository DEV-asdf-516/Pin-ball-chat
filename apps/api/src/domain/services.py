import hashlib
import json
from dataclasses import dataclass

from ai.registry import generate_text, runtime_params
from core.db import new_id, now, select_cols
from core.errors import NotFound
from domain.prompts import build_prompt


@dataclass
class GenerationParams:
    model: str = "local-stub"
    adapter_id: str | None = None
    num_predict: int | None = None
    num_ctx: int | None = None
    compact_prompt: bool = True
    provider_name: str | None = None


def save_generation_output(conn, turn_id, conversation_id, plot, char, user, params: GenerationParams, prompt, warnings, output, action_type, provider_meta=None, stream=False):
    candidate_index = conn.execute("SELECT COUNT(*) n FROM generations WHERE turn_id=?", (turn_id,)).fetchone()["n"]
    gen_id, msg_id, ts = new_id("gen"), new_id("msg"), now()
    user_message = conn.execute("SELECT content FROM messages WHERE turn_id=? AND role='user' ORDER BY created_at DESC LIMIT 1", (turn_id,)).fetchone()["content"]
    stored_params = {
        "warnings": warnings,
        "compactPrompt": params.compact_prompt,
        **runtime_params(params.provider_name, params.model, prompt, user_message, stream, params.num_predict, params.num_ctx),
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
            plot["id"],
            char["id"],
            user["id"],
            params.model,
            params.adapter_id,
            candidate_index,
            prompt,
            hashlib.sha256(prompt.encode()).hexdigest(),
            output,
            json.dumps(stored_params, ensure_ascii=False),
            len(output.split()),
            ts,
        ),
    )
    conn.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,?)", (msg_id, conversation_id, "assistant", output, turn_id, gen_id, ts))
    conn.execute("INSERT INTO user_actions VALUES (?,?,?,?,?,?,?)", (new_id("act"), conversation_id, turn_id, gen_id, action_type, None, ts))
    conn.commit()
    return {"generationId": gen_id, "messageId": msg_id, "candidateIndex": candidate_index}


def insert_user_turn(conn, conversation_id, message, msg_id, turn_id, ts):
    conn.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,?)", (msg_id, conversation_id, "user", message, turn_id, None, ts))
    conn.execute("INSERT INTO turns VALUES (?,?,?,?,?,?,?,?)", (turn_id, conversation_id, msg_id, None, 0, "open", ts, ts))


def mark_regenerated(conn, conversation_id, turn_id, current_generation_id):
    if current_generation_id:
        conn.execute("UPDATE generations SET rejected=1 WHERE id=?", (current_generation_id,))
    conn.execute("UPDATE turns SET regenerate_count=regenerate_count+1, updated_at=? WHERE id=?", (now(), turn_id))
    conn.execute(
        "INSERT INTO user_actions VALUES (?,?,?,?,?,?,?)",
        (new_id("act"), conversation_id, turn_id, current_generation_id, "generation_regenerated", None, now()),
    )


def record_generation(conn, turn_id, conversation_id, user_message, params: GenerationParams):
    prompt, warnings, plot, char, user = build_prompt(conn, conversation_id, user_message)
    candidate_index = conn.execute("SELECT COUNT(*) n FROM generations WHERE turn_id=?", (turn_id,)).fetchone()["n"]
    output, provider_meta = generate_text(prompt, user_message, params.model, candidate_index, params.num_predict, params.num_ctx, params.provider_name)
    saved = save_generation_output(conn, turn_id, conversation_id, plot, char, user, params, prompt, warnings, output, "generation_shown", provider_meta)
    return {"generationId": saved["generationId"], "turnId": turn_id, "output": output, "candidateIndex": saved["candidateIndex"]}


def create_conversation(conn, plot_id, title=None):
    plot = conn.execute(f"SELECT {select_cols('plots')} FROM plots WHERE id=?", (plot_id,)).fetchone()
    if not plot:
        raise NotFound("plot not found")
    if not conn.execute("SELECT 1 FROM characters WHERE id=?", (plot["character_id"],)).fetchone():
        raise NotFound("plot character missing")
    if not conn.execute("SELECT 1 FROM user_profiles WHERE id=?", (plot["user_profile_id"],)).fetchone():
        raise NotFound("plot user_profile missing")
    conv_id, ts = new_id("conv"), now()
    conn.execute("INSERT INTO conversations VALUES (?,?,?,?,?,?)", (conv_id, plot_id, title, None, ts, ts))
    conn.commit()
    return {"conversationId": conv_id, "plotId": plot_id}


def chat(conn, conversation_id, message, params: GenerationParams):
    ts = now()
    msg_id, turn_id = new_id("msg"), new_id("turn")
    prompt, warnings, plot, char, user = build_prompt(conn, conversation_id, message)
    output, provider_meta = generate_text(prompt, message, params.model, 0, params.num_predict, params.num_ctx, params.provider_name)
    insert_user_turn(conn, conversation_id, message, msg_id, turn_id, ts)
    saved = save_generation_output(conn, turn_id, conversation_id, plot, char, user, params, prompt, warnings, output, "generation_shown", provider_meta)
    return {"generationId": saved["generationId"], "turnId": turn_id, "output": output, "candidateIndex": saved["candidateIndex"]}


def prepare_chat_stream(conn, conversation_id, message):
    ts = now()
    msg_id, turn_id = new_id("msg"), new_id("turn")
    prompt, warnings, plot, char, user = build_prompt(conn, conversation_id, message)
    return {
        "conversationId": conversation_id,
        "turnId": turn_id,
        "messageId": msg_id,
        "createdAt": ts,
        "userMessage": message,
        "prompt": prompt,
        "warnings": warnings,
        "plot": plot,
        "char": char,
        "user": user,
        "actionType": "generation_shown",
    }


def regenerate(conn, turn_id, params: GenerationParams):
    turn = conn.execute(f"SELECT {select_cols('turns')} FROM turns WHERE id=?", (turn_id,)).fetchone()
    if not turn:
        raise NotFound("turn not found")
    current = conn.execute(
        f"SELECT {select_cols('generations')} FROM generations WHERE turn_id=? ORDER BY candidate_index DESC LIMIT 1",
        (turn_id,),
    ).fetchone()
    user_msg = conn.execute("SELECT content FROM messages WHERE id=?", (turn["user_message_id"],)).fetchone()["content"]
    prompt, warnings, plot, char, user = build_prompt(conn, turn["conversation_id"], user_msg)
    candidate_index = conn.execute("SELECT COUNT(*) n FROM generations WHERE turn_id=?", (turn_id,)).fetchone()["n"]
    output, provider_meta = generate_text(prompt, user_msg, params.model, candidate_index, params.num_predict, params.num_ctx, params.provider_name)
    mark_regenerated(conn, turn["conversation_id"], turn_id, current["id"] if current else None)
    saved = save_generation_output(conn, turn_id, turn["conversation_id"], plot, char, user, params, prompt, warnings, output, "generation_regenerated", provider_meta)
    return {"generationId": saved["generationId"], "turnId": turn_id, "output": output, "candidateIndex": saved["candidateIndex"]}


def prepare_regenerate_stream(conn, turn_id):
    turn = conn.execute(f"SELECT {select_cols('turns')} FROM turns WHERE id=?", (turn_id,)).fetchone()
    if not turn:
        raise NotFound("turn not found")
    current = conn.execute(
        f"SELECT {select_cols('generations')} FROM generations WHERE turn_id=? ORDER BY candidate_index DESC LIMIT 1",
        (turn_id,),
    ).fetchone()
    user_message = conn.execute("SELECT content FROM messages WHERE id=?", (turn["user_message_id"],)).fetchone()["content"]
    prompt, warnings, plot, char, user = build_prompt(conn, turn["conversation_id"], user_message)
    return {
        "conversationId": turn["conversation_id"],
        "turnId": turn_id,
        "currentGenerationId": current["id"] if current else None,
        "userMessage": user_message,
        "prompt": prompt,
        "warnings": warnings,
        "plot": plot,
        "char": char,
        "user": user,
        "actionType": "generation_regenerated",
    }


def select_generation(conn, generation_id):
    gen = conn.execute(f"SELECT {select_cols('generations')} FROM generations WHERE id=?", (generation_id,)).fetchone()
    if not gen:
        raise NotFound("generation not found")
    conn.execute("UPDATE turns SET selected_generation_id=?, updated_at=? WHERE id=?", (generation_id, now(), gen["turn_id"]))
    conn.execute("UPDATE generations SET selected=0 WHERE turn_id=?", (gen["turn_id"],))
    conn.execute("UPDATE generations SET rejected=1 WHERE turn_id=? AND id<>?", (gen["turn_id"], generation_id))
    conn.execute("UPDATE generations SET selected=1,rejected=0 WHERE id=?", (generation_id,))
    conn.execute(
        "INSERT INTO user_actions VALUES (?,?,?,?,?,?,?)",
        (new_id("act"), gen["conversation_id"], gen["turn_id"], generation_id, "generation_selected", None, now()),
    )
    conn.commit()
    return {"generationId": generation_id, "selected": True}


def edit_generation(conn, generation_id, edited_text):
    gen = conn.execute(f"SELECT {select_cols('generations')} FROM generations WHERE id=?", (generation_id,)).fetchone()
    if not gen:
        raise NotFound("generation not found")
    conn.execute(
        "INSERT INTO generation_edits VALUES (?,?,?,?,?)",
        (new_id("edit"), generation_id, gen["output_text"], edited_text, now()),
    )
    conn.execute(
        "INSERT INTO user_actions VALUES (?,?,?,?,?,?,?)",
        (new_id("act"), gen["conversation_id"], gen["turn_id"], generation_id, "generation_edited", None, now()),
    )
    conn.commit()
    return {"generationId": generation_id, "edited": True}

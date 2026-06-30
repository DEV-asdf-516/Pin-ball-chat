import json
import re

from core.db import select_cols
from core.errors import NotFound


def row_json(row, key):
    return json.loads(row[key])


def parse_roleplay_input(text):
    ooc = []
    body_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("OOC:"):
            ooc.append(stripped[4:].strip())
        else:
            body_lines.append(line)
    body = "\n".join(body_lines).strip()
    narrations = [match.group(1).strip() for match in re.finditer(r"\*([^*]+)\*", body) if match.group(1).strip()]
    dialogue = re.sub(r"\*[^*]+\*", "", body)
    dialogue = re.sub(r"[ \t]+", " ", dialogue).strip()
    return {"dialogue": dialogue, "narration": "\n".join(narrations), "ooc": "\n".join(ooc)}


def user_input_interpretation(text):
    parsed = parse_roleplay_input(text)
    return "\n".join([
        "사용자 대사:",
        parsed["dialogue"] or "(없음)",
        "",
        "사용자가 직접 확정한 자기 캐릭터 서술:",
        parsed["narration"] or "(없음)",
        "",
        "사용자 생성 요청:",
        parsed["ooc"] or "(없음)",
    ])


def render_value(value, ctx, warnings):
    if isinstance(value, str):
        def replace(match):
            name = match.group(1).strip()
            if name not in ctx:
                warnings.append(f"unknown template variable: {name}")
                return ""
            return ctx[name]
        return re.sub(r"\{\{\s*([^}]+)\s*\}\}", replace, value)
    if isinstance(value, list):
        return "\n".join(render_value(v, ctx, warnings) for v in value)
    if isinstance(value, dict):
        return "\n".join(f"{k}: {render_value(v, ctx, warnings)}" for k, v in value.items())
    return "" if value is None else str(value)


def split_ooc(text):
    body, ooc = [], []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("OOC:"):
            ooc.append(stripped[4:].strip())
        else:
            body.append(line)
    return "\n".join(body).strip(), ooc


def render_json_source(payload):
    return json.dumps(payload, ensure_ascii=False, indent=2)


def source_for(payload, source_text):
    return source_text if source_text else render_json_source(payload)


def resolve_prompt_context(conn, conversation_id):
    conv = conn.execute(f"SELECT {select_cols('conversations')} FROM conversations WHERE id=?", (conversation_id,)).fetchone()
    if not conv:
        raise NotFound("conversation not found")
    plot = conn.execute(f"SELECT {select_cols('plots')} FROM plots WHERE id=?", (conv["plot_id"],)).fetchone()
    if not plot:
        raise NotFound("conversation plot missing")
    char = conn.execute(f"SELECT {select_cols('characters')} FROM characters WHERE id=?", (plot["character_id"],)).fetchone()
    if not char:
        raise NotFound("plot character missing")
    user = conn.execute(f"SELECT {select_cols('user_profiles')} FROM user_profiles WHERE id=?", (plot["user_profile_id"],)).fetchone()
    if not user:
        raise NotFound("plot user_profile missing")
    return conv, plot, char, user


def merged_preferences(conn, plot, conversation_id):
    plot_data = row_json(plot, "plot_json")
    genres = plot_data.get("genre") or []
    if isinstance(genres, str):
        genres = [genres]
    rows = conn.execute(f"SELECT {select_cols('preference_profiles')} FROM preference_profiles").fetchall()
    chosen = []
    rank = {"global": 0, "genre": 1, "character": 2, "plot": 3, "conversation": 4}
    for row in rows:
        scope, sid = row["scope"], row["scope_id"]
        if scope == "global" or (scope == "genre" and sid in genres) or (scope == "character" and sid == plot["character_id"]) or (scope == "plot" and sid == plot["id"]) or (scope == "conversation" and sid == conversation_id):
            chosen.append((rank.get(scope, -1), row_json(row, "profile_json"), row["source_text"]))
    merged = {"preferredNotes": [], "dislikedPatterns": [], "generationRules": [], "inputMarkup": []}
    pref_ooc = []
    for _, payload, _ in sorted(chosen):
        profile = payload.get("profile", payload)
        for key, value in profile.items():
            if key in ("preferredNotes", "dislikedPatterns", "generationRules", "inputMarkup") and isinstance(value, list):
                merged.setdefault(key, []).extend(value)
            elif key not in ("id", "type", "scope", "scopeId", "sourceText"):
                merged[key] = value
        if isinstance(payload.get("ooc"), list):
            pref_ooc.extend(payload["ooc"])
    return merged, pref_ooc


def build_prompt(conn, conversation_id, user_message):
    _, plot, char, user = resolve_prompt_context(conn, conversation_id)
    char_data, user_data, plot_data = row_json(char, "profile_json"), row_json(user, "profile_json"), row_json(plot, "plot_json")
    ctx = {
        "char": char_data.get("displayName") or char_data.get("name") or char["id"],
        "user": user_data.get("displayName") or user_data.get("name") or user["id"],
        "plot": plot_data.get("title") or plot["id"],
    }
    warnings = []
    pref, pref_ooc = merged_preferences(conn, plot, conversation_id)
    parts = []
    ooc = []
    for title, payload, source in [
        ("캐릭터 프로필", char_data, char["source_text"]),
        ("사용자 프로필", user_data, user["source_text"]),
        ("플롯 프로필", plot_data, plot["source_text"]),
    ]:
        rendered = render_value(source_for(payload, source), ctx, warnings)
        body, found_ooc = split_ooc(rendered)
        parts.append((title, body))
        ooc.extend(found_ooc)
    recent = conn.execute(
        "SELECT role, content FROM messages WHERE conversation_id=? ORDER BY created_at DESC LIMIT 12",
        (conversation_id,),
    ).fetchall()
    recent_text = "\n".join(f"{r['role']}: {r['content']}" for r in reversed(recent))
    generation_rules = [
        *[render_value(r, ctx, warnings) for r in pref.get("generationRules", [])],
        *[f"선호: {render_value(n, ctx, warnings)}" for n in pref.get("preferredNotes", [])],
        *[f"금지: {render_value(p, ctx, warnings)}" for p in pref.get("dislikedPatterns", [])],
        *ooc,
        *[render_value(o, ctx, warnings) for o in pref_ooc],
    ]
    input_markup = [render_value(m, ctx, warnings) for m in pref.get("inputMarkup", [])]
    prompt = [
        render_value("[역할]\n너는 {{char}}다. {{user}}(사용자)의 메시지에 {{char}}로 응답한다.", ctx, warnings),
        *[f"[{title}]\n{body}" for title, body in parts],
        "[입력 표기]\n" + "\n".join(f"- {line}" for line in input_markup if line),
        "[현재 입력]\n" + user_input_interpretation(user_message),
        "[생성 규칙]\n" + "\n".join(f"- {line}" for line in generation_rules if line),
        "[최근 대화]\n" + recent_text,
        "[사용자 원문]\n" + render_value(user_message, ctx, warnings),
        "RESPOND NOW in Korean only. Do not explain, reason, translate, or plan. Output the roleplay scene directly.",
    ]
    return "\n\n".join(prompt), warnings, plot, char, user

import json
import re
import sqlite3
from dataclasses import dataclass

from core.db import fetch_all, find_by_id, select_cols
from core.errors import NotFound
from domain.content.reader import find_content_by_id
from domain.content.specs import CharacterData, ContentKind, PlotData, UserProfileData, parse_content_data
from util.dict_util import get_safe_list
from util.string_util import strip_from


_OOC_PREFIX = "OOC:"


@dataclass
class BuiltPrompt:
    prompt: str
    warnings: list
    plot: dict
    char: dict
    user: dict


def row_json(row: sqlite3.Row | dict, key: str) -> dict:
    return json.loads(row[key])


def parse_roleplay_input(text: str, ctx: dict) -> dict:
    ooc: list[str] = []
    body_lines: list[str] = []
    for line in text.splitlines():
        stripped: str = line.strip()
        if stripped.startswith(_OOC_PREFIX):
            ooc.append(substitute_npc_pc(strip_from(stripped, len(_OOC_PREFIX)), ctx))
        else:
            body_lines.append(line)
    body: str = "\n".join(body_lines).strip()
    narrations: list[str] = [match.group(1).strip() for match in re.finditer(r"\*([^*]+)\*", body) if match.group(1).strip()]
    dialogue: str = re.sub(r"\*[^*]+\*", "", body)
    dialogue = re.sub(r"[ \t]+", " ", dialogue).strip()
    return {"dialogue": dialogue, "narration": "\n".join(narrations), "ooc": "\n".join(ooc)}


def user_input_interpretation(text: str, ctx: dict) -> str:
    parsed: dict = parse_roleplay_input(text, ctx)
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


def render_value(value, ctx: dict, warnings: list) -> str:
    if isinstance(value, str):
        def replace(match: re.Match) -> str:
            name: str = match.group(1).strip()
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


def substitute_npc_pc(text: str, ctx: dict) -> str:
    """OOC 등 사용자 원문에 평문으로 등장하는 NPC/PC 표기를 실제 캐릭터명으로 치환한다."""
    text = re.sub(r"(?<![A-Za-z0-9])NPC(?![A-Za-z0-9])", ctx["char"], text)
    text = re.sub(r"(?<![A-Za-z0-9])PC(?![A-Za-z0-9])", ctx["user"], text)
    return text


def split_ooc(text: str) -> tuple[str, list[str]]:
    body: list[str] = []
    ooc: list[str] = []
    for line in text.splitlines():
        stripped: str = line.strip()
        if stripped.startswith(_OOC_PREFIX):
            ooc.append(strip_from(stripped, len(_OOC_PREFIX)))
        else:
            body.append(line)
    return "\n".join(body).strip(), ooc


def render_json_source(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def source_for(payload: dict, source_text: str | None) -> str:
    return source_text if source_text else render_json_source(payload)


def resolve_prompt_context(conn: sqlite3.Connection, conversation_id: str) -> tuple[dict, dict, dict, dict]:
    conv: dict | None = find_by_id(conn, "conversations", conversation_id)
    if not conv:
        raise NotFound("conversation not found")
    plot: dict | None = find_content_by_id(conn, ContentKind.PLOT, conv["plot_id"])
    if not plot:
        raise NotFound("conversation plot missing")
    char: dict | None = find_content_by_id(conn, ContentKind.CHARACTER, plot["character_id"])
    if not char:
        raise NotFound("plot character missing")
    user: dict | None = find_content_by_id(conn, ContentKind.USER_PROFILE, plot["user_profile_id"])
    if not user:
        raise NotFound("plot user_profile missing")
    return conv, plot, char, user


def merged_preferences(conn: sqlite3.Connection, plot: dict, conversation_id: str) -> tuple[dict, list]:
    plot_data: PlotData = parse_content_data(ContentKind.PLOT, row_json(plot, "plot_json"))
    genres: list[str] = plot_data.genre
    pref_rows: list[sqlite3.Row] = fetch_all(conn, f"SELECT {select_cols('preference_profiles')} FROM preference_profiles")
    chosen: list[tuple] = []
    rank: dict = {"global": 0, "genre": 1, "character": 2, "plot": 3, "conversation": 4}
    for row in pref_rows:
        scope, sid = row["scope"], row["scope_id"]
        if scope == "global" or (scope == "genre" and sid in genres) or (scope == "character" and sid == plot["character_id"]) or (scope == "plot" and sid == plot["id"]) or (scope == "conversation" and sid == conversation_id):
            chosen.append((rank.get(scope, -1), parse_content_data(ContentKind.PREFERENCE, row_json(row, "profile_json")), row["source_text"]))
    merged: dict = {"preferredNotes": [], "dislikedPatterns": [], "generationRules": [], "inputMarkup": []}
    pref_ooc: list = []
    for _, payload, _ in sorted(chosen, key=lambda item: item[0]):
        profile: dict = payload.profile
        for key, value in profile.items():
            if key in ("preferredNotes", "dislikedPatterns", "generationRules", "inputMarkup") and isinstance(value, list):
                merged.setdefault(key, []).extend(value)
            elif key not in ("id", "type", "scope", "scopeId", "sourceText"):
                merged[key] = value
        pref_ooc.extend(payload.ooc)
    return merged, pref_ooc


def build_prompt(conn: sqlite3.Connection, conversation_id: str, user_message: str) -> BuiltPrompt:
    _, plot, char, user = resolve_prompt_context(conn, conversation_id)
    char_json: dict = row_json(char, "profile_json")
    user_json: dict = row_json(user, "profile_json")
    plot_json: dict = row_json(plot, "plot_json")
    char_data: CharacterData = parse_content_data(ContentKind.CHARACTER, char_json)
    user_data: UserProfileData = parse_content_data(ContentKind.USER_PROFILE, user_json)
    plot_data: PlotData = parse_content_data(ContentKind.PLOT, plot_json)
    ctx: dict = {
        "char": char_data.displayName or char_data.name or char["id"],
        "user": user_data.displayName or user_data.name or user["id"],
        "plot": plot_data.title or plot["id"],
    }
    warnings: list = []
    pref, pref_ooc = merged_preferences(conn, plot, conversation_id)
    parts: list[tuple[str, str]] = []
    ooc: list[str] = []
    for title, payload, source in [
        ("캐릭터 프로필", char_json, char["source_text"]),
        ("사용자 프로필", user_json, user["source_text"]),
        ("플롯 프로필", plot_json, plot["source_text"]),
    ]:
        rendered: str = render_value(source_for(payload, source), ctx, warnings)
        body, found_ooc = split_ooc(rendered)
        parts.append((title, body))
        ooc.extend(found_ooc)
    recent: list[sqlite3.Row] = fetch_all(
        conn,
        "SELECT role, content FROM messages WHERE conversation_id=? ORDER BY created_at DESC LIMIT 12",
        (conversation_id,),
    )
    recent_text: str = "\n".join(f"{r['role']}: {r['content']}" for r in reversed(recent))
    generation_rules: list[str] = [
        *[render_value(r, ctx, warnings) for r in get_safe_list(pref, "generationRules")],
        *[f"선호: {render_value(n, ctx, warnings)}" for n in get_safe_list(pref, "preferredNotes")],
        *[f"금지: {render_value(p, ctx, warnings)}" for p in get_safe_list(pref, "dislikedPatterns")],
        *ooc,
        *[render_value(o, ctx, warnings) for o in pref_ooc],
    ]
    input_markup: list[str] = [render_value(m, ctx, warnings) for m in get_safe_list(pref, "inputMarkup")]
    prompt: list[str] = [
        render_value("[역할]\n너는 {{char}}다. {{user}}(사용자)의 메시지에 {{char}}로 응답한다.", ctx, warnings),
        *[f"[{title}]\n{body}" for title, body in parts],
        "[입력 표기]\n" + "\n".join(f"- {line}" for line in input_markup if line),
        "[현재 입력]\n" + user_input_interpretation(user_message, ctx),
        "[생성 규칙]\n" + "\n".join(f"- {line}" for line in generation_rules if line),
        "[최근 대화]\n" + recent_text,
        "[사용자 원문]\n" + render_value(user_message, ctx, warnings),
        "RESPOND NOW in Korean only. Do not explain, reason, translate, or plan. Output the roleplay scene directly.",
    ]
    return BuiltPrompt(prompt="\n\n".join(prompt), warnings=warnings, plot=plot, char=char, user=user)

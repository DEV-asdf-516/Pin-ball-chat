import json
import re
import sqlite3
from dataclasses import dataclass

from ai.specs import Message
from core.db import fetch_all, find_all, find_one
from core.errors import get_or_raise
from domain.catalog.reader import find_catalog_by_id
from domain.catalog.specs import SPEC_BY_KIND, CharacterData, CatalogKind, PlotData, UserProfileData, parse_catalog_data
from domain.conversations.specs import CONVERSATIONS
from util.safe_util import get_safe_list


_OOC_PATTERN = re.compile(
    r"[\[\{\*]+\s*OOC:\s*(?P<wrapped>.*?)\s*[\]\}\*]+"
    r"|OOC:\s*(?P<bare>.*)$",
    re.IGNORECASE,
)


@dataclass
class BuiltPrompt:
    system: str
    messages: list[Message]
    warnings: list
    plot: dict
    char: dict
    user: dict


def row_json(row: sqlite3.Row | dict, key: str) -> dict:
    return json.loads(row[key])


def extract_ooc(text: str) -> tuple[str, list[str]]:
    """OOC 지시문을 `[OOC: ...]`/`*OOC: ...*`/줄 안 아무 데서나 나오는 맨 `OOC:` 세 형태 모두 인식해 분리한다.
    OOC만 있던 줄은 통째로 빠지고, 다른 내용과 같은 줄에 있던 OOC는 그 부분만 잘라낸다."""
    ooc: list[str] = []

    def replace(match: re.Match) -> str:
        ooc.append((match.group("wrapped") or match.group("bare") or "").strip())
        return ""

    body_lines: list[str] = []
    
    for line in text.splitlines():
        remainder: str = _OOC_PATTERN.sub(replace, line).strip()
        if remainder:
            body_lines.append(remainder)
        elif not _OOC_PATTERN.search(line):
            body_lines.append(line)

    return "\n".join(body_lines), ooc


def parse_roleplay_input(text: str, ctx: dict) -> dict:
    body, ooc_lines = extract_ooc(text)
    ooc: list[str] = [substitute_npc_pc(line, ctx) for line in ooc_lines]
    narrations: list[str] = [match.group(1).strip() 
                             for match in re.finditer(r"\*([^*]+)\*", body) 
                             if match.group(1).strip()]
    dialogue: str = re.sub(r"\*[^*]+\*", "", body)
    dialogue = re.sub(r"[ \t]+", " ", dialogue).strip()
    
    return {
        "dialogue": dialogue, 
        "narration": "\n".join(narrations), 
        "ooc": "\n".join(ooc)
        }


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
    """OOC 등 사용자 원문에 평문으로 등장하는 NPC/PC 표기를 실제 캐릭터명으로 치환한다.
    (NPC)/{NPC}/(PC)/{PC}처럼 괄호로 감싼 표기는 괄호까지 통째로, 맨 단어는 단어 경계로 치환한다."""
    text = re.sub(r"[(\{]NPC[)\}]|(?<![A-Za-z0-9])NPC(?![A-Za-z0-9])", ctx["char"], text)
    text = re.sub(r"[(\{]PC[)\}]|(?<![A-Za-z0-9])PC(?![A-Za-z0-9])", ctx["user"], text)
    return text


def render_json_source(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def source_for(payload: dict, source_text: str | None) -> str:
    return source_text if source_text else render_json_source(payload)


def resolve_prompt_context(conn: sqlite3.Connection, conversation_id: str) -> tuple[dict, dict, dict, dict]:
    conv_row: dict | None = find_one(conn, CONVERSATIONS, conversation_id)
    conv: dict = get_or_raise(conv_row, "conversation not found")

    plot_row: dict | None = find_catalog_by_id(conn, CatalogKind.PLOT, conv["plot_id"])
    plot: dict = get_or_raise(plot_row, "conversation plot missing")

    char_row: dict | None = find_catalog_by_id(conn, CatalogKind.CHARACTER, plot["character_id"])
    char: dict = get_or_raise(char_row, "plot character missing")

    user_row: dict | None = find_catalog_by_id(conn, CatalogKind.USER_PROFILE, plot["user_profile_id"])
    user: dict = get_or_raise(user_row, "plot user_profile missing")

    return conv, plot, char, user


def merged_preferences(conn: sqlite3.Connection, plot: dict, conversation_id: str) -> tuple[dict, list]:
    plot_data: PlotData = parse_catalog_data(CatalogKind.PLOT, row_json(plot, "plot_json"))
    genres: list[str] = plot_data.genre
    pref_rows: list[dict] = find_all(conn, SPEC_BY_KIND[CatalogKind.PREFERENCE])
    chosen: list[tuple] = []
    rank: dict = {"global": 0, "genre": 1, "character": 2, "plot": 3, "conversation": 4}
    
    for row in pref_rows:
        scope, sid = row["scope"], row["scope_id"]
        if scope == "global" or (scope == "genre" and sid in genres) or (scope == "character" and sid == plot["character_id"]) or (scope == "plot" and sid == plot["id"]) or (scope == "conversation" and sid == conversation_id):
            chosen.append((rank.get(scope, -1), parse_catalog_data(CatalogKind.PREFERENCE, row_json(row, "profile_json")), row["source_text"]))
    
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


def _wrap_tag(tag: str, content: str) -> str:
    return f"<{tag}>\n{content}\n</{tag}>"


def snapshot_text(system: str, messages: list[Message]) -> str:
    return system + "\n\n" + "\n".join(f"{m.role}: {m.content}" for m in messages)


def build_prompt(conn: sqlite3.Connection, conversation_id: str, user_message: str) -> BuiltPrompt:
    _, plot, char, user = resolve_prompt_context(conn, conversation_id)
    char_json: dict = row_json(char, "profile_json")
    user_json: dict = row_json(user, "profile_json")
    plot_json: dict = row_json(plot, "plot_json")
    char_data: CharacterData = parse_catalog_data(CatalogKind.CHARACTER, char_json)
    user_data: UserProfileData = parse_catalog_data(CatalogKind.USER_PROFILE, user_json)
    plot_data: PlotData = parse_catalog_data(CatalogKind.PLOT, plot_json)
    ctx: dict = {
        "char": char_data.display_name or char_data.name or char["id"],
        "user": user_data.display_name or user_data.name or user["id"],
        "plot": plot_data.title or plot["id"],
    }
    warnings: list = []
    pref, pref_ooc = merged_preferences(conn, plot, conversation_id)
    parts: list[tuple[str, str]] = []
    ooc: list[str] = []
    for tag, payload, source in [
        ("character_profile", char_json, char["source_text"]),
        ("user_profile", user_json, user["source_text"]),
        ("plot_profile", plot_json, plot["source_text"]),
    ]:
        rendered: str = render_value(source_for(payload, source), ctx, warnings)
        body, found_ooc = extract_ooc(rendered)
        parts.append((tag, body))
        ooc.extend(found_ooc)
    recent: list[sqlite3.Row] = fetch_all(
        conn,
        """
        SELECT m.role, m.content
        FROM messages m
        LEFT JOIN generations g ON m.generation_id = g.id
        WHERE m.conversation_id=? AND (m.generation_id IS NULL OR g.rejected=0)
        ORDER BY m.rowid DESC
        LIMIT 12
        """,
        (conversation_id,),
    )
    generation_rules: list[str] = [
        *[render_value(r, ctx, warnings) for r in get_safe_list(pref, "generationRules")],
        *[f"선호: {render_value(n, ctx, warnings)}" for n in get_safe_list(pref, "preferredNotes")],
        *[f"금지: {render_value(p, ctx, warnings)}" for p in get_safe_list(pref, "dislikedPatterns")],
        *ooc,
        *[render_value(o, ctx, warnings) for o in pref_ooc],
    ]
    input_markup: list[str] = [render_value(m, ctx, warnings) for m in get_safe_list(pref, "inputMarkup")]
    system: str = "\n\n".join([
        _wrap_tag("role", render_value("너는 {{char}}다. {{user}}(사용자)의 메시지에 {{char}}로 응답한다.", ctx, warnings)),
        *[_wrap_tag(tag, body) for tag, body in parts],
        _wrap_tag("input_notation", "\n".join(f"- {line}" for line in input_markup if line)),
        _wrap_tag("generation_rules", "\n".join(f"- {line}" for line in generation_rules if line)),
        "RESPOND NOW in Korean only. Do not explain, reason, translate, or plan. Output the roleplay scene directly.",
    ])
    messages: list[Message] = [
        *[Message(role=r["role"], content=r["content"]) for r in reversed(recent)],
        Message(role="user", content=_wrap_tag("current_input", user_input_interpretation(user_message, ctx))),
    ]
    return BuiltPrompt(system=system, messages=messages, warnings=warnings, plot=plot, char=char, user=user)

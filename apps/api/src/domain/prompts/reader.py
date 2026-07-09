import json
import re
import sqlite3
from dataclasses import dataclass

from ai.specs import Message
from core.db import ROOT, fetch_all, find_all, find_one
from core.errors import get_or_raise
from domain.catalog.reader import find_catalog_by_id
from domain.catalog.specs import SPEC_BY_KIND, CharacterData, CatalogKind, PlotData, UserProfileData, parse_catalog_data
from domain.conversations.specs import CONVERSATIONS


_OOC_PATTERN = re.compile(
    r"[\[\{\*]+\s*OOC:\s*(?P<wrapped>.*?)\s*[\]\}\*]+"
    r"|OOC:\s*(?P<bare>.*)$",
    re.IGNORECASE,
)

_SYSTEM_PROMPT_PATH = ROOT / "rules" / "system_prompt.json"
_SYSTEM_PROMPT: dict = json.loads(_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8"))


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


def tag(name: str, content: str) -> str:
    return f"<{name}>\n{content.strip()}\n</{name}>"


def described(description: str, name: str, content: str) -> str:
    return f"{description}\n{tag(name, content)}"


def _section_text(key: str) -> str:
    return "\n".join(_SYSTEM_PROMPT[key].get("content", []))


def snapshot_text(system: str, messages: list[Message]) -> str:
    return system + "\n\n" + "\n".join(f"{m.role}: {m.content}" for m in messages)


def build_prompt(conn: sqlite3.Connection, conversation_id: str, user_message: str) -> BuiltPrompt:
    """system_prompt.json에 정의된 관찰자 프롬프트 골격 위에, 이 conversation의 캐릭터/유저/플롯 데이터를 채워 넣는다.
    TODO: preferences.json을 로어북처럼 쓰는 방식으로 나중에 다시 연결한다."""
    
    _, plot, char, user = resolve_prompt_context(conn, conversation_id)
    char_json: dict = row_json(char, "profile_json")
    user_json: dict = row_json(user, "profile_json")
    plot_json: dict = row_json(plot, "plot_json")
    char_data: CharacterData = parse_catalog_data(CatalogKind.CHARACTER, char_json)
    user_data: UserProfileData = parse_catalog_data(CatalogKind.USER_PROFILE, user_json)
    plot_data: PlotData = parse_catalog_data(CatalogKind.PLOT, plot_json)
    ctx: dict = {
        "char": char_data.name or char_data.display_name or char["id"],
        "user": user_data.name or user_data.display_name or user["id"],
        "plot": plot_data.title or plot["id"],
    }
    warnings: list = []

    char_body, _ = extract_ooc(render_value(source_for(char_json, char["source_text"]), ctx, warnings))
    user_body, _ = extract_ooc(render_value(source_for(user_json, user["source_text"]), ctx, warnings))
    plot_body, _ = extract_ooc(render_value(source_for(plot_json, plot["source_text"]), ctx, warnings))

    recent: list[sqlite3.Row] = fetch_all(
        conn,
        """
        SELECT m.role, m.content
        FROM messages m
        LEFT JOIN generations g ON m.generation_id = g.id
        WHERE m.conversation_id=? AND (m.generation_id IS NULL OR g.rejected=0)
        ORDER BY m.rowid DESC
        LIMIT 20
        """,
        (conversation_id,),
    )

    story_body: str = "\n\n".join([
        tag("title", ctx["plot"]),
        tag("information", plot_body),
        f'<char name="{ctx["char"]}" role="assistant">\n{char_body}\n</char>',
        f'<char name="관찰자" role="assistant">\n{_SYSTEM_PROMPT["story"]["observer_char"]}\n</char>',
        f'<user name="{ctx["user"]}" role="user">\n{user_body}\n</user>',
    ])

    system: str = "\n\n".join([
        described(_SYSTEM_PROMPT["system"]["description"], "system", render_value(_section_text("system"), ctx, warnings)),
        described(_SYSTEM_PROMPT["story"]["description"], "story", story_body),
        described(_SYSTEM_PROMPT["style"]["description"], "style", ""),
        described(_SYSTEM_PROMPT["mandatory_rules"]["description"], "mandatory_rules", render_value(_section_text("mandatory_rules"), ctx, warnings)),
        described(_SYSTEM_PROMPT["output_format"]["description"], "output_format", render_value(_section_text("output_format"), ctx, warnings)),
    ])
    messages: list[Message] = [
        *[Message(role=r["role"], content=r["content"]) for r in reversed(recent)],
        Message(role="user", content=described(_SYSTEM_PROMPT["current_input_description"], "current_input", user_input_interpretation(user_message, ctx))),
    ]
    return BuiltPrompt(system=system, messages=messages, warnings=warnings, plot=plot, char=char, user=user)

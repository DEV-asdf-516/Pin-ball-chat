import json
import re
import sqlite3

from core.db import ReadQuery, find_one
from core.errors import get_or_raise
from domain.catalog.reader import find_catalog_by_id
from domain.catalog.specs import CharacterData, CatalogKind, PlotData, UserProfileData, parse_catalog_data
from domain.conversations.specs import CONVERSATIONS

# build_prompt()가 최근 RECENT_WINDOW개 메시지는 항상 원문으로 넣고, 그보다 오래돼 밀려난 메시지가
# SUMMARY_TRIGGER개 이상 쌓였을 때만 요약을 갱신한다 (system/reader.py, summary/writer.py가 공유).
RECENT_WINDOW = 20
SUMMARY_TRIGGER = 10


def row_json(row: sqlite3.Row | dict, key: str) -> dict:
    return json.loads(row[key])


def resolve_prompt_context(conn: sqlite3.Connection, conversation_id: str) -> tuple[dict, dict, dict, dict]:
    conv_row: dict | None = find_one(conn, ReadQuery.by_id(CONVERSATIONS, conversation_id))
    conv: dict = get_or_raise(conv_row, "conversation not found")

    plot_row: dict | None = find_catalog_by_id(conn, CatalogKind.PLOT, conv["plot_id"])
    plot: dict = get_or_raise(plot_row, "conversation plot missing")

    char_row: dict | None = find_catalog_by_id(conn, CatalogKind.CHARACTER, plot["character_id"])
    char: dict = get_or_raise(char_row, "plot character missing")

    user_row: dict | None = find_catalog_by_id(conn, CatalogKind.USER_PROFILE, conv["user_profile_id"])
    user: dict = get_or_raise(user_row, "conversation has no user_profile set (select one before chatting)")

    return conv, plot, char, user


def build_ctx(plot: dict, char: dict, user: dict) -> dict:
    # {{char}}/{{user}}/{{plot}} 템플릿 변수 치환에 쓰는 표시 이름 dict. system/reader.py의 build_prompt()와
    # summary/writer.py의 maybe_update_summary()가 공유한다 — 둘 다 같은 대화의 캐릭터/유저/플롯을 가리키므로.
    char_data: CharacterData = parse_catalog_data(CatalogKind.CHARACTER, row_json(char, "profile_json"))
    user_data: UserProfileData = parse_catalog_data(CatalogKind.USER_PROFILE, row_json(user, "profile_json"))
    plot_data: PlotData = parse_catalog_data(CatalogKind.PLOT, row_json(plot, "plot_json"))
    return {
        "char": char_data.name or char_data.display_name or char["id"],
        "user": user_data.name or user_data.display_name or user["id"],
        "plot": plot_data.title or plot["id"],
    }


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


def tag(name: str, content: str) -> str:
    return f"<{name}>\n{content.strip()}\n</{name}>"


def described(description: str, name: str, content: str) -> str:
    return f"{description}\n{tag(name, content)}"

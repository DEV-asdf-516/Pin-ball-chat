import sqlite3

from core.errors import NotFound
from domain.content.reader import find_content_by_id
from domain.content.specs import ContentKind


def get_character(conn: sqlite3.Connection, character_id: str) -> dict:
    row: dict | None = find_content_by_id(conn, ContentKind.CHARACTER, character_id)
    if not row:
        raise NotFound(f"character {character_id} not found")
    return row

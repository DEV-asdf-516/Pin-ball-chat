import sqlite3

from core.db import exists, find_all, find_by_id
from domain.content.specs import KIND_TABLE, ContentKind


def find_content_by_id(conn: sqlite3.Connection, kind: ContentKind, item_id: str) -> dict | None:
    return find_by_id(conn, KIND_TABLE[kind], item_id)


def content_exists(conn: sqlite3.Connection, kind: ContentKind, value: str, column: str = "id") -> bool:
    return exists(conn, KIND_TABLE[kind], column, value)


def find_all_content(conn: sqlite3.Connection, kind: ContentKind) -> list[dict]:
    return find_all(conn, KIND_TABLE[kind])

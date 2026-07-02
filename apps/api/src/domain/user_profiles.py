import sqlite3

from core.errors import NotFound
from domain.content.reader import find_content_by_id
from domain.content.specs import ContentKind


def get_user_profile(conn: sqlite3.Connection, user_profile_id: str) -> dict:
    row: dict | None = find_content_by_id(conn, ContentKind.USER_PROFILE, user_profile_id)
    if not row:
        raise NotFound(f"user_profile {user_profile_id} not found")
    return row

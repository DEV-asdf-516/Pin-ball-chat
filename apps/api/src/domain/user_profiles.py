import sqlite3

from core.errors import get_or_raise
from domain.catalog.reader import find_catalog_by_id
from domain.catalog.specs import CatalogKind


def get_user_profile(conn: sqlite3.Connection, user_profile_id: str) -> dict:
    row: dict | None = find_catalog_by_id(conn, CatalogKind.USER_PROFILE, user_profile_id)
    return get_or_raise(row, f"user_profile {user_profile_id} not found")

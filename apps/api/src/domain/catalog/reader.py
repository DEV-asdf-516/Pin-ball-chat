import sqlite3

from core.db import CursorQuery, RawSQL, ReadQuery, exists, find_one, paginate, select_cols
from domain.catalog.specs import SPEC_BY_KIND, CatalogKind


def find_catalog_by_id(conn: sqlite3.Connection, kind: CatalogKind, item_id: str) -> dict | None:
    return find_one(conn, ReadQuery.by_id(SPEC_BY_KIND[kind], item_id))


def is_catalog_exists(conn: sqlite3.Connection, kind: CatalogKind, value: str, column: str = "id") -> bool:
    return exists(conn, ReadQuery.by_id(SPEC_BY_KIND[kind], value, column))


def list_catalog_by_kind(conn: sqlite3.Connection, kind: CatalogKind, before: int | None = None, limit: int = 100) -> dict:
    limit = max(1, min(limit, 200))
    table: str = SPEC_BY_KIND[kind].table
    params: dict = {"before": before} if before is not None else {}

    cursor_query = CursorQuery(
        query=RawSQL(f"""
        SELECT rowid, {select_cols(table)}
        FROM {table}
        {CursorQuery.clause("rowid", before)}
        ORDER BY rowid DESC
        LIMIT :limit
        """),
        params=params,
        limit=limit,
    )
    page: dict = paginate(conn, cursor_query)

    return {
        "items": page["items"],
        "nextCursor": page["nextCursor"],
        "hasMore": page["hasMore"],
    }

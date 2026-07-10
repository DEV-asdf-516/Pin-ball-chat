import sqlite3

from core.db import ReadQuery, exists, find_all, find_one
from domain.catalog.specs import SPEC_BY_KIND, CatalogKind


def find_catalog_by_id(conn: sqlite3.Connection, kind: CatalogKind, item_id: str) -> dict | None:
    return find_one(conn, ReadQuery.by_id(SPEC_BY_KIND[kind], item_id))


def is_catalog_exists(conn: sqlite3.Connection, kind: CatalogKind, value: str, column: str = "id") -> bool:
    return exists(conn, ReadQuery.by_id(SPEC_BY_KIND[kind], value, column))


def find_all_by_kind(conn: sqlite3.Connection, kind: CatalogKind) -> list[dict]:
    return find_all(conn, ReadQuery(SPEC_BY_KIND[kind]))

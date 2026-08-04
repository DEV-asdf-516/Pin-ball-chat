import sqlite3
from pathlib import Path

from core.db import DATA_ROOT, RawSQL, fetch_one
from core.errors import Conflict
from core.errors import get_or_raise
from domain.catalog.reader import find_catalog_by_id
from domain.catalog.specs import CatalogKind
from domain.catalog.writer import create_catalog_item, delete_catalog_item, update_catalog_item
from util.safe_util import get_or_default

MAX_PLOT_CHARACTERS = 10


def get_character(conn: sqlite3.Connection, character_id: str) -> dict:
    row: dict | None = find_catalog_by_id(conn, CatalogKind.CHARACTER, character_id)
    return get_or_raise(row, f"character {character_id} not found")


def _plot_character_count(conn: sqlite3.Connection, plot_id: str) -> int:
    row: sqlite3.Row = fetch_one(conn,
        RawSQL("""
            SELECT COUNT(*) AS count
            FROM characters
            WHERE plot_id=:plot_id
            """
        ),
        {"plot_id": plot_id},
    )
    return int(row["count"])


def create_character(conn: sqlite3.Connection, data: dict, root: Path = DATA_ROOT) -> dict:
    plot_id: str | None = get_or_default(data, "plotId", fallback_key="plot_id")

    if not plot_id:
        raise ValueError("plotId is required")

    if _plot_character_count(conn, plot_id) >= MAX_PLOT_CHARACTERS:
        raise Conflict("a plot can have at most 10 characters")

    payload: dict = {
        "type": "character",
        **data,
        "plotId": plot_id,
        "sortOrder": get_or_default(data, "sortOrder", fallback_key="sort_order", default=0),
    }
    return create_catalog_item(conn, CatalogKind.CHARACTER, payload, root=root)


def update_character(
    conn: sqlite3.Connection,
    character_id: str,
    data: dict,
    root: Path = DATA_ROOT
) -> dict:
    current: dict = get_character(conn, character_id)
    requested_plot_id: str | None = get_or_default(data, "plotId", fallback_key="plot_id")

    if requested_plot_id is not None and requested_plot_id != current["plot_id"]:
        raise Conflict("a character cannot be moved to another plot")

    payload: dict = {
        **data,
        "plotId": current["plot_id"],
        "sortOrder": get_or_default(
            data,
            "sortOrder",
            fallback_key="sort_order",
            default=current["sort_order"]
        ),
    }
    return update_catalog_item(conn, CatalogKind.CHARACTER, character_id, payload, root=root)


def delete_character(conn: sqlite3.Connection, character_id: str, root: Path = DATA_ROOT) -> dict:
    character: dict = get_character(conn, character_id)

    if _plot_character_count(conn, character["plot_id"]) <= 1:
        raise Conflict("a plot must have at least one character")

    return delete_catalog_item(conn, CatalogKind.CHARACTER, character_id, root=root)

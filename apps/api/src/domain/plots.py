import sqlite3

from core.errors import get_or_raise
from domain.catalog.reader import find_catalog_by_id
from domain.catalog.specs import CatalogKind


def get_plot(conn: sqlite3.Connection, plot_id: str) -> dict:
    row: dict | None = find_catalog_by_id(conn, CatalogKind.PLOT, plot_id)
    return get_or_raise(row, f"plot {plot_id} not found")

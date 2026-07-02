import sqlite3

from core.errors import NotFound
from domain.content.reader import find_content_by_id
from domain.content.specs import ContentKind


def get_plot(conn: sqlite3.Connection, plot_id: str) -> dict:
    row: dict | None = find_content_by_id(conn, ContentKind.PLOT, plot_id)
    if not row:
        raise NotFound(f"plot {plot_id} not found")
    return row

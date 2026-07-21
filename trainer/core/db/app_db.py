# Read-only access to the pinballchat application database, for dataset export.

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from dbkit import RawSQL, fetch_all

from ..errors import AppDbUnavailable
from ...domain.datasets import validate_format


@contextmanager
def app_db_connection() -> Iterator[sqlite3.Connection]:
    # Open the operating application's database with SQLite read-only mode.
    db_path: Path = Path(os.environ.get(
        "APP_DB_PATH", "./data/pinballchat.sqlite")).resolve()
    try:
        conn: sqlite3.Connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise AppDbUnavailable("could not open application database read-only") from exc

    conn.row_factory = sqlite3.Row

    try:
        yield conn
    finally:
        conn.close()


def export_application_rows(conn: sqlite3.Connection, dataset_format: str) -> list[dict[str, Any]]:
    # SFT/DPO export queries.
    dataset_format = validate_format(dataset_format)
    if dataset_format == "chat":
        rows: list[sqlite3.Row] = fetch_all(
            conn,
            RawSQL("""
                SELECT
                    e.edited_text,
                    g.prompt_snapshot,
                    m.content AS user_message
                FROM generation_edits e
                JOIN generations g ON g.id = e.generation_id
                JOIN turns t ON t.id = g.turn_id
                JOIN messages m ON m.id = t.user_message_id
                WHERE e.id = (
                    SELECT e2.id FROM generation_edits e2
                    WHERE e2.generation_id = e.generation_id
                    ORDER BY e2.created_at DESC, e2.id DESC
                    LIMIT 1
                )
            """),
        )
        return [
            {
                "messages": [
                    {"role": "system", "content": row["prompt_snapshot"]},
                    {"role": "user", "content": row["user_message"]},
                    {"role": "assistant", "content": row["edited_text"]},
                ]
            }
            for row in rows
        ]
    rows = fetch_all(
        conn,
        RawSQL("""
            SELECT 
                selected.prompt_snapshot, 
                selected.output_text AS chosen,
                rejected.output_text AS rejected
            FROM turns
            JOIN generations AS selected 
            ON selected.id = turns.selected_generation_id
            JOIN generations AS rejected
            ON rejected.turn_id = turns.id
            AND rejected.rejected = 1
            AND rejected.id <> selected.id
            WHERE turns.selected_generation_id IS NOT NULL
        """),
    )
    return [
        {
            "messages": [{"role": "system", "content": row["prompt_snapshot"]}],
            "chosen": row["chosen"],
            "rejected": row["rejected"],
        }
        for row in rows
    ]

# Read-only access to the pinballchat application database, for dataset export.

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from dbkit import RawSQL, fetch_all

from ..errors import AppDbUnavailable
from ...domain.datasets import validate_format


@contextmanager
def app_db_connection() -> Generator[sqlite3.Connection]:
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
                    g.prompt_messages_json
                FROM generation_edits e
                JOIN generations g ON g.id = e.generation_id
                WHERE e.id = (
                    SELECT e2.id FROM generation_edits e2
                    WHERE e2.generation_id = e.generation_id
                    ORDER BY e2.created_at DESC, e2.id DESC
                    LIMIT 1
                )
                AND g.prompt_messages_json IS NOT NULL
            """),
        )
        rows_out: list[dict[str, Any]] = []
        for row in rows:
            prompt: dict[str, Any] = json.loads(row["prompt_messages_json"])
            rows_out.append({
                "messages": [
                    {"role": "system", "content": prompt["system"]},
                    *prompt["messages"],
                    {"role": "assistant", "content": row["edited_text"]},
                ]
            })
        return rows_out
    rows = fetch_all(
        conn,
        RawSQL("""
            SELECT
                selected.prompt_messages_json,
                selected.output_text AS chosen,
                rejected.output_text AS rejected
            FROM turns
            JOIN generations AS selected
            ON selected.id = turns.selected_generation_id
            JOIN generations AS rejected
            ON rejected.turn_id = turns.id
            AND rejected.rejected = 1
            AND rejected.id <> selected.id
            AND rejected.prompt_hash = selected.prompt_hash
            AND rejected.model_id = selected.model_id
            AND rejected.adapter_id IS selected.adapter_id
            WHERE turns.selected_generation_id IS NOT NULL
            AND selected.prompt_messages_json IS NOT NULL
        """),
    )
    preference_rows: list[dict[str, Any]] = []
    for row in rows:
        prompt = json.loads(row["prompt_messages_json"])
        preference_rows.append({
            "messages": [
                {"role": "system", "content": prompt["system"]},
                *prompt["messages"],
            ],
            "chosen": row["chosen"],
            "rejected": row["rejected"],
        })
    return preference_rows

"""SQLite access for trainer-only job state."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from dbkit import TableSpec, init_db


SCHEMA = """
CREATE TABLE IF NOT EXISTS training_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    type        TEXT NOT NULL CHECK (type IN ('TRAIN','REGISTER')),
    status      TEXT NOT NULL DEFAULT 'QUEUED'
                CHECK (status IN ('QUEUED','RUNNING','DONE','FAILED')),
    datasets    TEXT,
    recipe      TEXT,
    output_name TEXT NOT NULL,
    parent_run_id INTEGER,
    log_path    TEXT,
    error       TEXT,
    created_at  TEXT NOT NULL,
    started_at  TEXT,
    finished_at TEXT
);
"""

TABLE_NAMES: list[str] = ["training_runs"]

# id는 autoincrement라 insert 시 항상 raw SQL로 남긴다(TRAIN/REGISTER가 서로 다른 컬럼 subset을 쓰고
# cursor.lastrowid가 필요함) — 그래서 TableSpec.columns는 find_one/find_all/update 등 조회·갱신 경로에서만 쓰인다.
TRAINING_RUNS = TableSpec(
    table="training_runs",
    columns=(
        "type",
        "status",
        "datasets",
        "recipe",
        "output_name",
        "parent_run_id",
        "log_path",
        "error",
        "created_at",
        "started_at",
        "finished_at",
    ),
)


def trainer_db_path() -> Path:
    return Path(os.environ.get("TRAINER_DB_PATH", "./trainer/data/trainer.sqlite")).resolve()


def connect() -> sqlite3.Connection:
    path = trainer_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


def initialize() -> None:
    with connect() as connection:
        init_db(connection, SCHEMA, TABLE_NAMES)

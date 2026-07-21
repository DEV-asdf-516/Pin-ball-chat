# SQLite connection + schema init for the trainer's own job-queue database.

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from dbkit import init_db

from .schema import SCHEMA

TABLE_NAMES: list[str] = ["training_runs"]


def trainer_db_path() -> Path:
    return Path(os.environ.get("TRAINER_DB_PATH", "./trainer/data/trainer.sqlite")).resolve()


def connect() -> sqlite3.Connection:
    path: Path = trainer_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn: sqlite3.Connection = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def initialize() -> None:
    with connect() as conn:
        init_db(conn, SCHEMA, TABLE_NAMES)

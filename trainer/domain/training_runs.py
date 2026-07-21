# Training-run queue domain logic: validation, persistence, and derived reads.

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from dbkit import Bind, Direction, OrderBy, ReadQuery, find_all, find_one, insert

from ..core.db import TRAINING_RUNS
from ..core.errors import Conflict, get_or_raise
from ..util import utc_now
from .datasets import DatasetError, read_manifest, validate_name
from .recipes import get_recipe_backend
from .specs import Backend, DatasetFormat


def _deserialize_training_run(row: Any) -> dict[str, Any]:
    result: dict[str, Any] = dict(row)
    if result.get("datasets"):
        result["datasets"] = json.loads(result["datasets"])
    return result


def validate_training_inputs(datasets: list[str], recipe: str) -> list[dict[str, Any]]:
    # v0.1 training gate: chat-only datasets, mlx-only backend. Shared by the API
    # queue-time check (create_training_run) and train_lora.py's execution-time check —
    # keep this the single place that rule lives.
    manifests: list[dict[str, Any]] = []
    for dataset in datasets:
        manifest: dict[str, Any] = read_manifest(validate_name(dataset))
        if manifest["format"] != DatasetFormat.CHAT:
            raise DatasetError("v0.1 supports chat only")
        manifests.append(manifest)

    if get_recipe_backend(recipe) == Backend.CUDA:
        raise DatasetError("cuda backend is not implemented in v0.1")

    return manifests


def create_training_run(conn: sqlite3.Connection, datasets: list[str], recipe: str, output_name: str) -> dict[str, Any]:
    if not datasets:
        raise DatasetError("at least one dataset is required")

    output_name = validate_name(output_name)
    validate_training_inputs(datasets, recipe)

    cursor: sqlite3.Cursor = insert(conn, TRAINING_RUNS, Bind({
        "type": "TRAIN",
        "status": "QUEUED",
        "datasets": json.dumps(datasets),
        "recipe": recipe,
        "output_name": output_name,
        "created_at": utc_now(),
    }))
    row: dict[str, Any] | None = find_one(conn, ReadQuery.by_id(TRAINING_RUNS, cursor.lastrowid))
    return _deserialize_training_run(row)


def list_training_runs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = find_all(conn, ReadQuery(TRAINING_RUNS, order_by=(OrderBy("id", Direction.DESC),)))
    return [_deserialize_training_run(row) for row in rows]


def read_training_log(conn: sqlite3.Connection, run_id: int, tail: int) -> list[str]:
    row: dict[str, Any] = get_or_raise(
        find_one(conn, ReadQuery.by_id(TRAINING_RUNS, run_id)), 
        "training run not found"
    )
    log_path: str | None = row["log_path"]
    
    if not log_path or not Path(log_path).is_file():
        return []

    try:
        lines: list[str] = Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return lines[-tail:]


def register_training_run(conn: sqlite3.Connection, run_id: int) -> dict[str, Any]:
    parent: dict[str, Any] = get_or_raise(
        find_one(conn, ReadQuery.by_id(TRAINING_RUNS, run_id)), "training run not found"
    )
    if parent["type"] != "TRAIN" or parent["status"] != "DONE":
        raise Conflict("only completed training runs can be registered")

    cursor: sqlite3.Cursor = insert(conn, TRAINING_RUNS, Bind({
        "type": "REGISTER",
        "status": "QUEUED",
        "output_name": parent["output_name"],
        "parent_run_id": run_id,
        "created_at": utc_now(),
    }))
    row: dict[str, Any] | None = find_one(conn, ReadQuery.by_id(TRAINING_RUNS, cursor.lastrowid))
    return _deserialize_training_run(row)

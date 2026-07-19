"""Training-run queue and log endpoints."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from dbkit import Direction, OrderBy, ReadQuery, find_all, find_one

from .dataset_io import DatasetError, read_manifest, utc_now, validate_name
from .db import TRAINING_RUNS, connect


router = APIRouter(prefix="/api")


class TrainingRunRequest(BaseModel):
    datasets: list[str]
    recipe: str
    output_name: str


def _error(status: int, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": message})


def _row_dict(row: Any) -> dict[str, Any]:
    result = dict(row)
    if result.get("datasets"):
        result["datasets"] = json.loads(result["datasets"])
    return result


def _recipe_path(recipe: str) -> Path:
    if Path(recipe).name != recipe or not recipe.endswith(".yaml"):
        raise DatasetError("recipe does not exist")
    path = Path(os.environ.get("TRAINER_ROOT", "./trainer")).resolve() / "recipes" / recipe
    if not path.is_file():
        raise DatasetError("recipe does not exist")
    return path


def _recipe_backend(recipe: str) -> str:
    try:
        loaded = yaml.safe_load(_recipe_path(recipe).read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise DatasetError("recipe is invalid") from exc
    if not isinstance(loaded, dict) or loaded.get("backend") not in {"mlx", "cuda"}:
        raise DatasetError("recipe backend is invalid")
    return loaded["backend"]


@router.post("/training-runs", status_code=201)
def create_training_run(request: TrainingRunRequest) -> dict[str, Any]:
    try:
        if not request.datasets:
            raise DatasetError("at least one dataset is required")
        output_name = validate_name(request.output_name)
        for dataset in request.datasets:
            manifest = read_manifest(validate_name(dataset))
            if manifest["format"] == "preference":
                raise DatasetError("v0.1 supports chat only")
        backend = _recipe_backend(request.recipe)
        if backend == "cuda":
            raise DatasetError("cuda backend is not implemented in v0.1")
    except DatasetError as exc:
        raise _error(400, str(exc))

    with connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO training_runs (type, status, datasets, recipe, output_name, created_at)
            VALUES ('TRAIN', 'QUEUED', ?, ?, ?, ?)
            """,
            (json.dumps(request.datasets), request.recipe, output_name, utc_now()),
        )
        row = find_one(connection, ReadQuery.by_id(TRAINING_RUNS, cursor.lastrowid))
    return _row_dict(row)


@router.get("/training-runs")
def list_training_runs() -> dict[str, list[dict[str, Any]]]:
    with connect() as connection:
        rows = find_all(connection, ReadQuery(TRAINING_RUNS, order_by=(OrderBy("id", Direction.DESC),)))
    return {"runs": [_row_dict(row) for row in rows]}


@router.get("/training-runs/{run_id}/log")
def get_training_log(run_id: int, tail: int = Query(default=200, ge=1)) -> dict[str, list[str]]:
    with connect() as connection:
        row = find_one(connection, ReadQuery.by_id(TRAINING_RUNS, run_id))
    if row is None:
        raise _error(404, "training run not found")
    log_path = row["log_path"]
    if not log_path or not Path(log_path).is_file():
        return {"lines": []}
    try:
        lines = Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {"lines": []}
    return {"lines": lines[-tail:]}


@router.post("/training-runs/{run_id}/register", status_code=201)
def register_training_run(run_id: int) -> dict[str, Any]:
    with connect() as connection:
        parent = find_one(connection, ReadQuery.by_id(TRAINING_RUNS, run_id))
        if parent is None:
            raise _error(404, "training run not found")
        if parent["type"] != "TRAIN" or parent["status"] != "DONE":
            raise _error(409, "only completed training runs can be registered")
        cursor = connection.execute(
            """
            INSERT INTO training_runs (type, status, output_name, parent_run_id, created_at)
            VALUES ('REGISTER', 'QUEUED', ?, ?, ?)
            """,
            (parent["output_name"], run_id, utc_now()),
        )
        row = find_one(connection, ReadQuery.by_id(TRAINING_RUNS, cursor.lastrowid))
    return _row_dict(row)

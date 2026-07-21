# Training-run queue and log endpoints.

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from ...domain.training_runs import (
    create_training_run,
    list_training_runs,
    read_training_log,
    register_training_run,
)
from ..dependencies import DbConn
from ..specs import TrainingLogResponse, TrainingRunRequest, TrainingRunResponse, TrainingRunsPageResponse


router: APIRouter = APIRouter(prefix="/api")


@router.post("/training-runs", status_code=201, response_model=TrainingRunResponse)
def create_run(request: TrainingRunRequest, conn: DbConn) -> dict[str, Any]:
    return create_training_run(conn, request.datasets, request.recipe, request.output_name)


@router.get("/training-runs", response_model=TrainingRunsPageResponse)
def get_training_runs(conn: DbConn) -> dict[str, list[dict[str, Any]]]:
    return {"runs": list_training_runs(conn)}


@router.get("/training-runs/{run_id}/log", response_model=TrainingLogResponse)
def get_training_log(run_id: int, conn: DbConn, tail: int = Query(default=200, ge=1)) -> dict[str, list[str]]:
    return {"lines": read_training_log(conn, run_id, tail)}


@router.post("/training-runs/{run_id}/register", status_code=201, response_model=TrainingRunResponse)
def register_run(run_id: int, conn: DbConn) -> dict[str, Any]:
    return register_training_run(conn, run_id)

# Pydantic request/response DTOs for trainer/api routes.

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from ..domain.datasets import DatasetFormat


class TrainingRunRequest(BaseModel):
    datasets: list[str]
    recipe: str
    output_name: str


class TrainingRunResponse(BaseModel):
    id: int
    type: str
    status: str
    datasets: list[str] | None = None
    recipe: str | None = None
    output_name: str
    parent_run_id: int | None = None
    log_path: str | None = None
    error: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None


class TrainingRunsPageResponse(BaseModel):
    runs: list[TrainingRunResponse]


class TrainingLogResponse(BaseModel):
    lines: list[str]


class ExampleRequest(BaseModel):
    dataset: str
    format: DatasetFormat
    row: dict[str, Any]


class ExportRequest(BaseModel):
    name: str
    format: DatasetFormat
    generated_by: str


class DatasetWriteResponse(BaseModel):
    dataset: str
    row_count: int


class ImportDatasetResponse(DatasetWriteResponse):
    rejected_rows: int
    duplicates_removed: int


class DatasetManifestResponse(BaseModel):
    name: str
    source: str
    format: DatasetFormat
    row_count: int
    created_at: str
    origin: str
    generated_by: str | None = None


class DatasetsPageResponse(BaseModel):
    datasets: list[DatasetManifestResponse]
    invalid: list[str]


class RecipesResponse(BaseModel):
    recipes: list[str]

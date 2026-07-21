# Dataset collection, import, and application-export endpoints.

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Form, UploadFile

from ...core.db.app_db import app_db_connection, export_application_rows
from ...domain.datasets import (
    CreateDatasetParams,
    DatasetFormat,
    add_example_row,
    create_dataset_from_candidates,
    list_datasets,
)
from ...domain.importer import create_dataset_from_upload
from ...domain.recipes import list_recipes
from ..specs import (
    DatasetsPageResponse,
    DatasetWriteResponse,
    ExampleRequest,
    ExportRequest,
    ImportDatasetResponse,
    RecipesResponse,
)


router: APIRouter = APIRouter(prefix="/api")


@router.post("/examples", response_model=DatasetWriteResponse)
def add_example(request: ExampleRequest) -> dict[str, Any]:
    return add_example_row(request.dataset, request.format, request.row)


@router.post("/import", response_model=ImportDatasetResponse)
async def import_dataset(
    file: UploadFile = File(...), name: str = Form(...), format: DatasetFormat = Form(...)
) -> dict[str, Any]:
    raw: bytes = await file.read()
    return create_dataset_from_upload(name, format, raw, file.filename or "uploaded_file.jsonl")


@router.post("/export", response_model=DatasetWriteResponse)
def export_dataset(request: ExportRequest) -> dict[str, Any]:
    with app_db_connection() as conn:
        exported: list[dict[str, Any]] = export_application_rows(conn, request.format)
    
    params: CreateDatasetParams = CreateDatasetParams(
        request.name,
        request.format,
        source="app_export",
        origin=f"APP_DB_PATH export format={request.format}",
        generated_by=request.generated_by,
    )
    return create_dataset_from_candidates(params, exported)


@router.get("/datasets", response_model=DatasetsPageResponse)
def get_datasets() -> dict[str, Any]:
    datasets, invalid = list_datasets()
    return {"datasets": datasets, "invalid": invalid}


@router.get("/recipes", response_model=RecipesResponse)
def get_recipes() -> dict[str, list[str]]:
    return {"recipes": list_recipes()}

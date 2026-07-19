"""Dataset collection, import, and application-export endpoints."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from .dataset_io import (
    DatasetError,
    DatasetFormatMismatch,
    app_db_connection,
    append_row,
    canonical_hash,
    create_dataset,
    datasets_dir,
    export_application_rows,
    list_datasets,
    read_manifest,
    validate_format,
    validate_name,
    validate_row,
    write_rows,
)
from .importer import import_lines


router = APIRouter(prefix="/api")


class ExampleRequest(BaseModel):
    dataset: str
    format: str
    row: dict[str, Any]


class ExportRequest(BaseModel):
    name: str
    format: str
    generated_by: str


def api_error(status: int, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": message})


def _error_message(exc: Exception) -> str:
    return str(exc) or "invalid request"


@router.post("/examples")
def add_example(request: ExampleRequest) -> dict[str, Any]:
    try:
        name = validate_name(request.dataset)
        dataset_format = validate_format(request.format)
        validate_row(request.row, dataset_format)
        try:
            manifest = read_manifest(name)
        except DatasetError:
            if (datasets_dir() / name).exists():
                raise
            create_dataset(name, dataset_format, "manual", "manual")
            manifest = read_manifest(name)
        if manifest["format"] != dataset_format:
            raise DatasetFormatMismatch("dataset format does not match")
        row_count = append_row(name, dataset_format, request.row)
        return {"dataset": name, "row_count": row_count}
    except DatasetFormatMismatch as exc:
        raise api_error(409, _error_message(exc))
    except DatasetError as exc:
        raise api_error(400, _error_message(exc))


@router.post("/import")
async def import_dataset(
    file: UploadFile = File(...), name: str = Form(...), format: str = Form(...)
) -> dict[str, Any]:
    try:
        name = validate_name(name)
        dataset_format = validate_format(format)
        if (datasets_dir() / name).exists():
            raise api_error(409, "dataset already exists")
        raw = await file.read()
        try:
            lines = raw.decode("utf-8").splitlines()
        except UnicodeDecodeError as exc:
            raise DatasetError("uploaded file must be UTF-8 JSONL") from exc
        result = import_lines(lines, dataset_format)
        if not result.rows:
            raise api_error(400, "no valid rows")
        create_dataset(name, dataset_format, "import",
                       file.filename or "uploaded_file.jsonl")
        row_count = write_rows(name, dataset_format, result.rows)
        return {
            "dataset": name,
            "row_count": row_count,
            "rejected_rows": result.rejected_rows,
            "duplicates_removed": result.duplicates_removed,
        }
    except HTTPException:
        raise
    except FileExistsError:
        raise api_error(409, "dataset already exists")
    except DatasetError as exc:
        raise api_error(400, _error_message(exc))


@router.post("/export")
def export_dataset(request: ExportRequest) -> dict[str, Any]:
    try:
        name = validate_name(request.name)
        dataset_format = validate_format(request.format)
        if not request.generated_by.strip():
            raise DatasetError("generated_by is required for app_export")
        if (datasets_dir() / name).exists():
            raise api_error(409, "dataset already exists")
        with app_db_connection() as connection:
            exported = export_application_rows(connection, dataset_format)
        valid_rows = []
        seen = set()
        for row in exported:
            try:
                checked = validate_row(row, dataset_format)
            except DatasetError:
                continue
            fingerprint = canonical_hash(checked)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            valid_rows.append(checked)
        create_dataset(
            name,
            dataset_format,
            "app_export",
            f"APP_DB_PATH export format={dataset_format}",
            request.generated_by,
        )
        row_count = write_rows(name, dataset_format, valid_rows)
        return {"dataset": name, "row_count": row_count}
    except HTTPException:
        raise
    except FileExistsError:
        raise api_error(409, "dataset already exists")
    except DatasetError as exc:
        raise api_error(400, _error_message(exc))


@router.get("/datasets")
def get_datasets() -> dict[str, Any]:
    datasets, invalid = list_datasets()
    return {"datasets": datasets, "invalid": invalid}


@router.get("/recipes")
def get_recipes() -> dict[str, list[str]]:
    root = Path(os.environ.get("TRAINER_ROOT", "./trainer")
                ).resolve() / "recipes"
    return {"recipes": sorted(path.name for path in root.glob("*.yaml") if path.is_file())}

# Line-by-line dataset importer shared by the API and CLI.

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

from .datasets import (
    DatasetError,
    DatasetFormat,
    canonical_hash,
    create_dataset,
    validate_name,
    validate_row,
    write_rows,
)
from .specs import CreateDatasetParams


@dataclass(frozen=True)
class ImportResult:
    rows: list[dict[str, Any]]
    rejected_rows: int
    duplicates_removed: int


def import_lines(lines: Iterable[str], dataset_format: DatasetFormat) -> ImportResult:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    rejected_rows: int = 0
    duplicates_removed: int = 0
    
    for line in lines:
        try:
            parsed: object = json.loads(line)
            row: dict[str, Any] = validate_row(parsed, dataset_format)
        except (json.JSONDecodeError, DatasetError, TypeError):
            rejected_rows += 1
            continue
        
        row_hash: str = canonical_hash(row)
        
        if row_hash in seen:
            duplicates_removed += 1
            continue
        
        seen.add(row_hash)
        rows.append(row)
        
    return ImportResult(rows, rejected_rows, duplicates_removed)


def create_dataset_from_upload(name: str, dataset_format: DatasetFormat, raw: bytes, origin: str) -> dict[str, Any]:
    # Decode an uploaded JSONL file, import its rows, and create the dataset from them.
    name = validate_name(name)

    try:
        lines: list[str] = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise DatasetError("uploaded file must be UTF-8 JSONL") from exc

    result: ImportResult = import_lines(lines, dataset_format)
    
    if not result.rows:
        raise DatasetError("no valid rows")

    create_dataset(CreateDatasetParams(name, dataset_format, source="import", origin=origin))
    write_rows(name, dataset_format, result.rows)

    return {
        "dataset": name,
        "row_count": len(result.rows),
        "rejected_rows": result.rejected_rows,
        "duplicates_removed": result.duplicates_removed,
    }

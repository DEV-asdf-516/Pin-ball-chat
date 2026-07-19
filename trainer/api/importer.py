"""Line-by-line dataset importer shared by the API and CLI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, TextIO

from .dataset_io import DatasetError, canonical_hash, validate_row


@dataclass(frozen=True)
class ImportResult:
    rows: list[dict[str, Any]]
    rejected_rows: int
    duplicates_removed: int


def import_lines(lines: Iterable[str], dataset_format: str) -> ImportResult:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    rejected_rows = 0
    duplicates_removed = 0
    for line in lines:
        try:
            parsed = json.loads(line)
            row = validate_row(parsed, dataset_format)
        except (json.JSONDecodeError, DatasetError, TypeError):
            rejected_rows += 1
            continue
        row_hash = canonical_hash(row)
        if row_hash in seen:
            duplicates_removed += 1
            continue
        seen.add(row_hash)
        rows.append(row)
    return ImportResult(rows, rejected_rows, duplicates_removed)


def import_file(path: Path, dataset_format: str) -> ImportResult:
    with path.open("r", encoding="utf-8") as handle:
        return import_lines(handle, dataset_format)

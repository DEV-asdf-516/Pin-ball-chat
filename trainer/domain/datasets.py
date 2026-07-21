# Shared dataset-folder storage and validation helpers.

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

from ..util import trainer_root, utc_now
from .specs import CreateDatasetParams, DatasetError, DatasetFormat, DatasetFormatMismatch, ThinkingCheck


NAME_RE: re.Pattern[str] = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")

def _dataset_path(name: str) -> Path:
    return datasets_dir() / validate_name(name)


def _manifest_path(name: str) -> Path:
    return _dataset_path(name) / "manifest.json"

def _write_manifest(name: str, manifest: dict[str, Any]) -> None:
    content: str = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    _manifest_path(name).write_text(content, encoding="utf-8")

def _validate_content(value: object, field: str) -> str:
    # Check that value is a non-empty string and return it unchanged.
    if not isinstance(value, str) or not value.strip():
        raise DatasetError(f"{field} must be a non-empty string")
    return value

def _validate_messages(value: object) -> list[dict[str, str]]:
    # Check that value is a well-formed messages array (each item has a valid role and non-empty content) and return it normalized to {role, content} dicts.
    if not isinstance(value, list) or not value:
        raise DatasetError("messages must be a non-empty array")

    messages: list[dict[str, str]] = []

    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise DatasetError(f"messages[{index}] must be an object")

        role: object = item.get("role")

        if role not in {"system", "user", "assistant"}:
            raise DatasetError(f"messages[{index}].role is invalid")

        messages.append({
            "role": role,
            "content": _validate_content(item.get("content"), f"messages[{index}].content")
        })

    return messages


def validate_name(name: object) -> str:
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise DatasetError("invalid dataset name")
    return name

def validate_format(dataset_format: object) -> DatasetFormat:
    try:
        return DatasetFormat(dataset_format)
    except ValueError:
        raise DatasetError("format must be chat or preference")

def validate_row(row: object, dataset_format: object) -> dict[str, Any]:
    # Validate a dataset row and return its original JSON-compatible object.
    dataset_format = validate_format(dataset_format)
    
    if not isinstance(row, dict):
        raise DatasetError("row must be an object")
    
    match dataset_format:
        case DatasetFormat.CHAT:
            messages: list[dict[str, str]] = _validate_messages(row.get("messages"))
            
            if messages[-1]["role"] != "assistant":
                raise DatasetError("the final message role must be assistant")

            # 생각 태그 검사 대상(assistant 메시지들)만 모아서 아래에서 한 번에 돈다.
            to_checks: list[ThinkingCheck] = [
                ThinkingCheck(f"messages[{index}].content", message["content"])
                for index, message in enumerate(messages)
                if message["role"] == "assistant"
            ]
        case DatasetFormat.PREFERENCE:
            to_checks = [ThinkingCheck("chosen", _validate_content(row.get("chosen"), "chosen"))]
            _validate_content(row.get("rejected"), "rejected")
        case _:
            raise DatasetError("format must be chat or preference")

    for check in to_checks:
        check.validate()

    # Preserve optional metadata while returning a detached, JSON-safe row.
    return json.loads(json.dumps(row, ensure_ascii=False))


def canonical_hash(row: dict[str, Any]) -> str:
    encoded: str = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

def datasets_dir() -> Path:
    path: Path = trainer_root() / "datasets"
    path.mkdir(parents=True, exist_ok=True)
    return path

def data_path(name: str) -> Path:
    return _dataset_path(name) / "data.jsonl"


def read_manifest(name: str) -> dict[str, Any]:
    def is_valid(manifest: object) -> bool:
        if not isinstance(manifest, dict) or manifest.get("name") != name:
            return False

        # format만 예외: validate_format()이 자기 메시지("format must be chat or preference")로 직접 raise한다.
        validate_format(manifest.get("format"))

        if manifest.get("source") not in {"manual", "import", "app_export"}:
            return False
        
        if not isinstance(manifest.get("row_count"), int) or manifest["row_count"] < 0:
            return False
        
        if not isinstance(manifest.get("created_at"), str) or not isinstance(manifest.get("origin"), str):
            return False
        
        generated_by: object = manifest.get("generated_by")
        
        if manifest["source"] == "app_export":
            return isinstance(generated_by, str) and bool(generated_by.strip())
        
        return generated_by is None

    path: Path = _manifest_path(name)

    try:
        manifest: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DatasetError(f"dataset {name} has an invalid manifest") from exc

    if not is_valid(manifest):
        raise DatasetError(f"dataset {name} has an invalid manifest")

    if not data_path(name).is_file():
        raise DatasetError(f"dataset {name} is missing data.jsonl")

    return manifest

def create_dataset(params: CreateDatasetParams) -> dict[str, Any]:
    name: str = validate_name(params.name)
    dataset_format: DatasetFormat = validate_format(params.dataset_format)
    directory: Path = _dataset_path(name)
    
    if directory.exists():
        raise FileExistsError(f"dataset {name} already exists")
    
    directory.mkdir(parents=True)
    data_path(name).touch()
    
    manifest: dict[str, Any] = {
        "name": name,
        "source": params.source,
        "format": dataset_format,
        "row_count": 0,
        "created_at": utc_now(),
        "origin": params.origin,
        "generated_by": params.generated_by if params.source == "app_export" else None,
    }
    _write_manifest(name, manifest)
    return manifest


def append_row(name: str, dataset_format: DatasetFormat, row: object) -> int:
    manifest: dict[str, Any] = read_manifest(name)
    
    if manifest["format"] != dataset_format:
        raise DatasetFormatMismatch("dataset format does not match")
    
    checked: dict[str, Any] = validate_row(row, dataset_format)
    
    with data_path(name).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(checked, ensure_ascii=False) + "\n")
    
    manifest["row_count"] = int(manifest.get("row_count", 0)) + 1
    
    _write_manifest(name, manifest)
    
    return manifest["row_count"]


def write_rows(name: str, dataset_format: DatasetFormat, rows: Iterable[dict[str, Any]]) -> int:
    manifest: dict[str, Any] = read_manifest(name)
    
    if manifest["format"] != dataset_format:
        raise DatasetFormatMismatch("dataset format does not match")
    
    rows : list = list(rows)
    
    with data_path(name).open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    
    manifest["row_count"] = len(rows)
    
    _write_manifest(name, manifest)
    
    return len(rows)


def add_example_row(name: str, dataset_format: DatasetFormat, row: object) -> dict[str, Any]:
    # Append a row to a dataset, creating it (as "manual") on first use.
    name = validate_name(name)
    validate_row(row, dataset_format)

    try:
        manifest: dict[str, Any] = read_manifest(name)
    except DatasetError:
        if _dataset_path(name).exists():
            raise
        create_dataset(CreateDatasetParams(name, dataset_format, source="manual", origin="manual"))
        manifest = read_manifest(name)

    if manifest["format"] != dataset_format:
        raise DatasetFormatMismatch("dataset format does not match")

    row_count: int = append_row(name, dataset_format, row)
    return {"dataset": name, "row_count": row_count}


def create_dataset_from_candidates(
    params: CreateDatasetParams, candidate_rows: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    # Validate and dedupe candidate rows, then create the dataset from what survives.
    valid_rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in candidate_rows:
        try:
            checked: dict[str, Any] = validate_row(row, params.dataset_format)
        except DatasetError:
            continue
        fingerprint: str = canonical_hash(checked)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        valid_rows.append(checked)

    create_dataset(params)
    write_rows(params.name, params.dataset_format, valid_rows)
    return {"dataset": params.name, "row_count": len(valid_rows)}


def list_datasets() -> tuple[list[dict[str, Any]], list[str]]:
    valid: list[dict[str, Any]] = []
    invalid: list[str] = []
    root: Path = datasets_dir()
    
    for directory in sorted(root.iterdir(), key=lambda item: item.name):
        if not directory.is_dir():
            continue
        try:
            name: str = validate_name(directory.name)
            valid.append(read_manifest(name))
        except DatasetError:
            invalid.append(directory.name)
    
    return valid, invalid

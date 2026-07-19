"""Shared dataset-folder storage and validation helpers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from dbkit import RawSQL, fetch_all


NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
THINKING_RE = re.compile(r"<\s*/?\s*(?:think|thinking)\b[^>]*>", re.IGNORECASE)
FORMATS = {"chat", "preference"}


class DatasetError(ValueError):
    """A request supplied an invalid dataset, name, or row."""


class DatasetFormatMismatch(DatasetError):
    """An existing dataset has a different format."""


def trainer_root() -> Path:
    return Path(os.environ.get("TRAINER_ROOT", "./trainer")).resolve()


def datasets_dir() -> Path:
    path = trainer_root() / "datasets"
    path.mkdir(parents=True, exist_ok=True)
    return path


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def validate_name(name: object) -> str:
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise DatasetError("invalid dataset name")
    return name


def validate_format(dataset_format: object) -> str:
    if dataset_format not in FORMATS:
        raise DatasetError("format must be chat or preference")
    return str(dataset_format)


def _content(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DatasetError(f"{field} must be a non-empty string")
    return value


def _messages(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise DatasetError("messages must be a non-empty array")
    messages: list[dict[str, str]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise DatasetError(f"messages[{index}] must be an object")
        role = item.get("role")
        if role not in {"system", "user", "assistant"}:
            raise DatasetError(f"messages[{index}].role is invalid")
        messages.append({"role": role, "content": _content(item.get("content"), f"messages[{index}].content")})
    return messages


def _reject_thinking(content: str, field: str) -> None:
    if THINKING_RE.search(content):
        raise DatasetError(f"{field} must not contain thinking tags")


def validate_row(row: object, dataset_format: object) -> dict[str, Any]:
    """Validate a dataset row and return its original JSON-compatible object."""
    dataset_format = validate_format(dataset_format)
    if not isinstance(row, dict):
        raise DatasetError("row must be an object")
    messages = _messages(row.get("messages"))
    if dataset_format == "chat":
        if messages[-1]["role"] != "assistant":
            raise DatasetError("the final message role must be assistant")
        for index, message in enumerate(messages):
            if message["role"] == "assistant":
                _reject_thinking(message["content"], f"messages[{index}].content")
    else:
        _reject_thinking(_content(row.get("chosen"), "chosen"), "chosen")
        _content(row.get("rejected"), "rejected")
    # Preserve optional metadata while returning a detached, JSON-safe row.
    return json.loads(json.dumps(row, ensure_ascii=False))


def canonical_hash(row: dict[str, Any]) -> str:
    encoded = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def dataset_path(name: str) -> Path:
    return datasets_dir() / validate_name(name)


def manifest_path(name: str) -> Path:
    return dataset_path(name) / "manifest.json"


def data_path(name: str) -> Path:
    return dataset_path(name) / "data.jsonl"


def read_manifest(name: str) -> dict[str, Any]:
    path = manifest_path(name)
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DatasetError(f"dataset {name} has an invalid manifest") from exc
    if not isinstance(manifest, dict) or manifest.get("name") != name:
        raise DatasetError(f"dataset {name} has an invalid manifest")
    validate_format(manifest.get("format"))
    if manifest.get("source") not in {"manual", "import", "app_export"}:
        raise DatasetError(f"dataset {name} has an invalid manifest")
    if not isinstance(manifest.get("row_count"), int) or manifest["row_count"] < 0:
        raise DatasetError(f"dataset {name} has an invalid manifest")
    if not isinstance(manifest.get("created_at"), str) or not isinstance(manifest.get("origin"), str):
        raise DatasetError(f"dataset {name} has an invalid manifest")
    if manifest["source"] == "app_export":
        if not isinstance(manifest.get("generated_by"), str) or not manifest["generated_by"].strip():
            raise DatasetError(f"dataset {name} has an invalid manifest")
    elif manifest.get("generated_by") is not None:
        raise DatasetError(f"dataset {name} has an invalid manifest")
    if not data_path(name).is_file():
        raise DatasetError(f"dataset {name} is missing data.jsonl")
    return manifest


def create_dataset(
    name: str,
    dataset_format: str,
    source: str,
    origin: str,
    generated_by: str | None = None,
) -> dict[str, Any]:
    name = validate_name(name)
    dataset_format = validate_format(dataset_format)
    if source not in {"manual", "import", "app_export"}:
        raise DatasetError("invalid dataset source")
    if source == "app_export" and (not isinstance(generated_by, str) or not generated_by.strip()):
        raise DatasetError("generated_by is required for app_export")
    directory = dataset_path(name)
    if directory.exists():
        raise FileExistsError(name)
    directory.mkdir(parents=True)
    data_path(name).touch()
    manifest = {
        "name": name,
        "source": source,
        "format": dataset_format,
        "row_count": 0,
        "created_at": utc_now(),
        "origin": origin,
        "generated_by": generated_by if source == "app_export" else None,
    }
    write_manifest(name, manifest)
    return manifest


def write_manifest(name: str, manifest: dict[str, Any]) -> None:
    manifest_path(name).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def append_row(name: str, dataset_format: str, row: object) -> int:
    manifest = read_manifest(name)
    if manifest["format"] != dataset_format:
        raise DatasetFormatMismatch("dataset format does not match")
    checked = validate_row(row, dataset_format)
    with data_path(name).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(checked, ensure_ascii=False) + "\n")
    manifest["row_count"] = int(manifest.get("row_count", 0)) + 1
    write_manifest(name, manifest)
    return manifest["row_count"]


def write_rows(name: str, dataset_format: str, rows: Iterable[dict[str, Any]]) -> int:
    manifest = read_manifest(name)
    if manifest["format"] != dataset_format:
        raise DatasetFormatMismatch("dataset format does not match")
    rows = list(rows)
    with data_path(name).open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    manifest["row_count"] = len(rows)
    write_manifest(name, manifest)
    return len(rows)


def list_datasets() -> tuple[list[dict[str, Any]], list[str]]:
    valid: list[dict[str, Any]] = []
    invalid: list[str] = []
    root = datasets_dir()
    for directory in sorted(root.iterdir(), key=lambda item: item.name):
        if not directory.is_dir():
            continue
        try:
            name = validate_name(directory.name)
            valid.append(read_manifest(name))
        except DatasetError:
            invalid.append(directory.name)
    return valid, invalid


def app_db_connection() -> sqlite3.Connection:
    """Open the operating application's database with SQLite read-only mode."""
    db_path = Path(os.environ.get("APP_DB_PATH", "./data/pinballchat.sqlite")).resolve()
    try:
        connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise DatasetError("could not open application database read-only") from exc
    connection.row_factory = sqlite3.Row
    return connection


def export_application_rows(connection: sqlite3.Connection, dataset_format: str) -> list[dict[str, Any]]:
    """Apply the existing SFT/DPO export queries and emit §2-compatible rows."""
    dataset_format = validate_format(dataset_format)
    if dataset_format == "chat":
        rows = fetch_all(
            connection,
            RawSQL("""
            SELECT e.edited_text, g.prompt_snapshot, m.content AS user_message
            FROM generation_edits e
            JOIN generations g ON g.id = e.generation_id
            JOIN turns t ON t.id = g.turn_id
            JOIN messages m ON m.id = t.user_message_id
            """),
        )
        return [
            {
                "messages": [
                    {"role": "system", "content": row["prompt_snapshot"]},
                    {"role": "user", "content": row["user_message"]},
                    {"role": "assistant", "content": row["edited_text"]},
                ]
            }
            for row in rows
        ]
    rows = fetch_all(
        connection,
        RawSQL("""
        SELECT selected.prompt_snapshot, selected.output_text AS chosen,
               rejected.output_text AS rejected
        FROM turns
        JOIN generations AS selected ON selected.id = turns.selected_generation_id
        JOIN generations AS rejected
          ON rejected.turn_id = turns.id
         AND rejected.rejected = 1
         AND rejected.id <> selected.id
        WHERE turns.selected_generation_id IS NOT NULL
        """),
    )
    return [
        {
            "messages": [{"role": "system", "content": row["prompt_snapshot"]}],
            "chosen": row["chosen"],
            "rejected": row["rejected"],
        }
        for row in rows
    ]

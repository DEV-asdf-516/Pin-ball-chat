# Reading/locating run-directory artifacts (run_meta.json) written by jobs/train_lora.py.
# export_gguf.py and worker/runner.py (REGISTER backend lookup) both read this file — keep
# the path and the backend-field validation in one place.

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .specs import Backend, DatasetError

RUN_META_FILENAME = "run_meta.json"


def run_meta_path(run_dir: Path) -> Path:
    return run_dir / RUN_META_FILENAME


def read_run_meta(run_dir: Path) -> dict[str, Any]:
    try:
        meta: object = json.loads(run_meta_path(run_dir).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DatasetError("run metadata is unavailable") from exc

    if not isinstance(meta, dict):
        raise DatasetError("run metadata is invalid")

    return meta


def run_backend(meta: dict[str, Any]) -> Backend:
    try:
        return Backend(meta.get("backend"))
    except ValueError:
        raise DatasetError("run backend is invalid") from None

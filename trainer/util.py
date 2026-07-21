# Domain-agnostic pure helpers — no DB, no dataset/training-run knowledge, no FastAPI.

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path


def trainer_root() -> Path:
    return Path(os.environ.get("TRAINER_ROOT", "./trainer")).resolve()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

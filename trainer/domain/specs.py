# Domain-level DTOs/value objects for trainer's dataset handling.

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

THINKING_RE: re.Pattern[str] = re.compile(r"<\s*/?\s*(?:think|thinking)\b[^>]*>", re.IGNORECASE)


class DatasetFormat(StrEnum):
    CHAT = "chat"
    PREFERENCE = "preference"


class Backend(StrEnum):
    MLX = "mlx"
    CUDA = "cuda"


class DatasetError(ValueError):
    # A request supplied an invalid dataset, name, or row.
    pass


class DatasetFormatMismatch(DatasetError):
    # An existing dataset has a different format.
    pass


@dataclass(frozen=True)
class ThinkingCheck:
    # validate_row()가 생각 태그 검사 대상을 모아뒀다가 한 번에 도는 용도. field는 에러 메시지 라벨.
    field: str
    content: str

    def validate(self) -> None:
        # Reject content that still contains a <think>/<thinking> tag.
        if THINKING_RE.search(self.content):
            raise DatasetError(f"{self.field} must not contain thinking tags")


@dataclass(frozen=True)
class CreateDatasetParams:
    name: str
    dataset_format: DatasetFormat
    source: str
    origin: str
    generated_by: str | None = None

    def __post_init__(self) -> None:
        if self.source not in {"manual", "import", "app_export"}:
            raise DatasetError("invalid dataset source")
        
        if self.source == "app_export" and (not isinstance(self.generated_by, str) or not self.generated_by.strip()):
            raise DatasetError("generated_by is required for app_export")

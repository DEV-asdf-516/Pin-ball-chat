from dataclasses import dataclass
from enum import StrEnum


class ActionType(StrEnum):
    # user_actions 로그에 남기는 이벤트 종류.
    GENERATION_SHOWN = "generation_shown"
    GENERATION_REGENERATED = "generation_regenerated"
    GENERATION_SELECTED = "generation_selected"
    GENERATION_EDITED = "generation_edited"
    IMPORT_COMMITTED = "import_committed"


@dataclass
class GenerationParams:
    model: str = "local-stub"
    adapter_id: str | None = None
    num_predict: int | None = None
    num_ctx: int | None = None
    compact_prompt: bool = True
    provider_name: str | None = None

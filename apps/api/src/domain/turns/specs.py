from dataclasses import dataclass
from enum import StrEnum

from core.db import TableSpec
from domain.prompts.system.reader import BuiltPrompt


class ActionType(StrEnum):
    # user_actions 로그에 남기는 이벤트 종류.
    GENERATION_SHOWN = "generation_shown"
    GENERATION_REGENERATED = "generation_regenerated"
    GENERATION_SELECTED = "generation_selected"
    GENERATION_EDITED = "generation_edited"


@dataclass
class PreparedGeneration:
    # prepare_chat_stream/prepare_regenerate_stream이 만들어서 stream_response에 넘기는 컨텍스트.
    # message_id/created_at은 chat일 때만, current_generation_id는 regenerate일 때만 채워진다.
    conversation_id: str
    turn_id: str
    user_message: str
    built: BuiltPrompt
    action_type: ActionType
    message_id: str | None = None
    created_at: str | None = None
    current_generation_id: str | None = None


MESSAGES = TableSpec(
    table="messages",
    columns=("id", "conversation_id", "role", "content", "turn_id", "generation_id", "created_at"),
)
TURNS = TableSpec(
    table="turns",
    columns=("id", "conversation_id", "user_message_id", "selected_generation_id", "regenerate_count", "status", "created_at", "updated_at"),
)
USER_ACTIONS = TableSpec(
    table="user_actions",
    columns=("id", "conversation_id", "turn_id", "generation_id", "action_type", "payload_json", "created_at"),
)
GENERATION_EDITS = TableSpec(
    table="generation_edits",
    columns=("id", "generation_id", "original_text", "edited_text", "created_at"),
)
GENERATIONS = TableSpec(
    table="generations",
    columns=(
        "id", "turn_id", "conversation_id", "plot_id", "character_id", "user_profile_id", "model_id", "adapter_id",
        "candidate_index", "prompt_snapshot", "prompt_hash", "output_text", "params_json", "output_token_count", "selected", "created_at",
    ),
)

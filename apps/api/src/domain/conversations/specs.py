from core.db import TableSpec

CONVERSATIONS = TableSpec(
    table="conversations",
    columns=("id", "plot_id", "user_profile_id", "title", "active_adapter_id", "created_at", "updated_at"),
)

CONVERSATION_SETTINGS = TableSpec(
    table="conversation_settings",
    columns=("conversation_id", "provider", "model", "num_predict", "num_ctx", "compact_prompt", "adapter_id", "created_at", "updated_at"),
    conflict_col="conversation_id",
)

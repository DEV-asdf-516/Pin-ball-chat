from core.db import TableSpec

CONVERSATIONS = TableSpec(
    table="conversations",
    columns=("id", "plot_id", "user_profile_id", "title", "active_adapter_id", "summary_text", "summary_through_rowid", "created_at", "updated_at"),
)

RECENT_WINDOW = 20
SUMMARY_TRIGGER = 10

CONVERSATION_SETTINGS = TableSpec(
    table="conversation_settings",
    columns=("conversation_id", "provider", "model", "num_predict", "num_ctx", "compact_prompt", "adapter_id", "created_at", "updated_at"),
    conflict_col="conversation_id",
)

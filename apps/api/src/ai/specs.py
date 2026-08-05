from dataclasses import dataclass
from enum import StrEnum


class ProviderName(StrEnum):
    LOCAL_STUB = "local-stub"
    OLLAMA = "ollama"
    OPENAI = "openai"
    OPENAI_CODEX = "openai-codex"
    ANTHROPIC = "anthropic"
    CLAUDE_CLI = "claude-cli"
    GEMINI = "gemini"

    @classmethod
    def connectable(cls) -> tuple["ProviderName", ...]:
        return tuple(p for p in cls if p is not cls.LOCAL_STUB)


class PromptTier(StrEnum):
    EXTERNAL = "external"
    LOCAL = "local"


@dataclass
class Message:
    role: str
    content: str


@dataclass
class GenerateRequest:
    system: str
    messages: list[Message]
    model: str
    candidate_index: int
    num_predict: int | None = None
    num_ctx: int | None = None
    stream: bool = False


@dataclass
class ProviderConnection:
    provider: ProviderName
    status: str
    credential_type: str
    action_required: str | None = None
    runtime_version: str | None = None
    resolved_auth_mode: str | None = None
    account_label: str | None = None
    plan: str | None = None
    verification_url: str | None = None
    user_code: str | None = None
    key_source: str | None = None

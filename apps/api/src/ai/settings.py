import os

DEFAULT_NUM_PREDICT = int(os.environ.get("DEFAULT_NUM_PREDICT", 160))
DEFAULT_NUM_CTX = int(os.environ.get("DEFAULT_NUM_CTX", 1024))
DEFAULT_AI_PROVIDER = os.environ.get("AI_PROVIDER", "ollama")

OLLAMA_KEEP_ALIVE = os.environ.get("OLLAMA_KEEP_ALIVE", "30m")
OLLAMA_OPTIONS = {"temperature": 0.8, "top_p": 0.9}
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", 300))
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL")

OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com")
OPENAI_TEMPERATURE = float(os.environ.get("OPENAI_TEMPERATURE", 0.9))
OPENAI_TIMEOUT = int(os.environ.get("OPENAI_TIMEOUT", 600))

ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
ANTHROPIC_API_VERSION = os.environ.get("ANTHROPIC_API_VERSION", "2023-06-01")
ANTHROPIC_TEMPERATURE = float(os.environ.get("ANTHROPIC_TEMPERATURE", 0.9))
ANTHROPIC_TIMEOUT = int(os.environ.get("ANTHROPIC_TIMEOUT", 600))

GEMINI_BASE_URL = os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com")
GEMINI_TEMPERATURE = float(os.environ.get("GEMINI_TEMPERATURE", 0.9))
GEMINI_TIMEOUT = int(os.environ.get("GEMINI_TIMEOUT", 600))

SSE_HEARTBEAT_SECONDS = int(os.environ.get("SSE_HEARTBEAT_SECONDS", 15))
RUNTIME_FIRST_DELTA_TIMEOUT = int(os.environ.get("RUNTIME_FIRST_DELTA_TIMEOUT", 90))
RUNTIME_IDLE_TIMEOUT = int(os.environ.get("RUNTIME_IDLE_TIMEOUT", 90))
RUNTIME_INTERRUPT_GRACE_SECONDS = int(os.environ.get("RUNTIME_INTERRUPT_GRACE_SECONDS", 10))
RUNTIME_QUEUE_SIZE = int(os.environ.get("RUNTIME_QUEUE_SIZE", 32))
RUNTIME_QUEUE_BLOCK_SECONDS = int(os.environ.get("RUNTIME_QUEUE_BLOCK_SECONDS", 10))
RUNTIME_LOGIN_TIMEOUT = int(os.environ.get("RUNTIME_LOGIN_TIMEOUT", 300))
RUNTIME_RESTART_BACKOFF_SECONDS = float(os.environ.get("RUNTIME_RESTART_BACKOFF_SECONDS", 1))
RUNTIME_STDOUT_LINE_LIMIT = int(os.environ.get("RUNTIME_STDOUT_LINE_LIMIT", 10 * 1024 * 1024))
CODEX_MAX_IN_FLIGHT = int(os.environ.get("CODEX_MAX_IN_FLIGHT", 1))
CLAUDE_MAX_IN_FLIGHT = int(os.environ.get("CLAUDE_MAX_IN_FLIGHT", 1))

PINBALLCHAT_RUNTIME_ROOT = os.environ.get("PINBALLCHAT_RUNTIME_ROOT", "/tmp/pinballchat-runtime")

CLAUDE_COMMAND = os.environ.get("CLAUDE_COMMAND", "claude")
CLAUDE_RUNTIME_VERSION = os.environ.get("CLAUDE_RUNTIME_VERSION", "2.1.195")
CLAUDE_MODELS = tuple(
    model.strip()
    for model in os.environ.get("CLAUDE_MODELS", "claude-sonnet-4-6,claude-opus-4-8,claude-haiku-4-5-20251001").split(",")
    if model.strip()
)

CODEX_COMMAND = os.environ.get("CODEX_COMMAND", "codex")
CODEX_RUNTIME_VERSION = os.environ.get("CODEX_RUNTIME_VERSION", "0.145.0-alpha.27")

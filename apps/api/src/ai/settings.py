import os

DEFAULT_NUM_PREDICT = int(os.environ.get("DEFAULT_NUM_PREDICT", 160))
DEFAULT_NUM_CTX = int(os.environ.get("DEFAULT_NUM_CTX", 1024))
DEFAULT_AI_PROVIDER = os.environ.get("AI_PROVIDER", "ollama")

OLLAMA_KEEP_ALIVE = os.environ.get("OLLAMA_KEEP_ALIVE", "30m")
OLLAMA_OPTIONS = {"temperature": 0.8, "top_p": 0.9}
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", 300))

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

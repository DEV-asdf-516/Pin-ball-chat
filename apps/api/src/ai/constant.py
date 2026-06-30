import os

DEFAULT_NUM_PREDICT = 160
DEFAULT_NUM_CTX = 1024
DEFAULT_AI_PROVIDER = os.environ.get("AI_PROVIDER", "ollama")

OLLAMA_KEEP_ALIVE = os.environ.get("OLLAMA_KEEP_ALIVE", "30m")
OLLAMA_OPTIONS = {"temperature": 0.8, "top_p": 0.9}
OLLAMA_TIMEOUT = 300

import os


def require_env(name: str) -> str:
    value: str | None = os.environ.get(name)
    if not value:
        raise ValueError(f"{name} is missing")
    return value

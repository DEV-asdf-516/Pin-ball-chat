import os
from typing import NamedTuple

from ai.specs import ProviderName
from core.secrets import delete_secret, read_secrets, write_secret


API_KEY_PROVIDERS: dict[ProviderName, str] = {
    ProviderName.OPENAI: "OPENAI_API_KEY",
    ProviderName.ANTHROPIC: "ANTHROPIC_API_KEY",
    ProviderName.GEMINI: "GEMINI_API_KEY",
}
_MAX_API_KEY_LENGTH = 4096


class LocatedKey(NamedTuple):
    key: str
    source: str


def _environment_key(env_name: str) -> str:
    return os.environ.get(env_name, "").strip()


def _locate_key(env_name: str) -> LocatedKey | None:
    stored_key = read_secrets().get(env_name)
    if stored_key:
        return LocatedKey(stored_key, "stored")

    environment_key = _environment_key(env_name)
    if environment_key:
        return LocatedKey(environment_key, "env")

    return None


def resolve_api_key(env_name: str) -> str:
    located_key = _locate_key(env_name)
    if located_key is None:
        raise ValueError(f"{env_name} is missing")
    return located_key.key


def stored_key_source(env_name: str) -> str | None:
    located_key = _locate_key(env_name)
    return located_key.source if located_key else None


def save_api_key(provider: ProviderName, key: str) -> None:
    cleaned = key.strip()
    if not cleaned:
        raise ValueError("api key must not be empty")
    if len(cleaned) > _MAX_API_KEY_LENGTH:
        raise ValueError("api key is too long")
    if provider not in API_KEY_PROVIDERS:
        raise ValueError(f"api key is not supported for provider: {provider}")

    write_secret(API_KEY_PROVIDERS[provider], cleaned)


def delete_api_key(provider: ProviderName) -> None:
    if provider not in API_KEY_PROVIDERS:
        raise ValueError(f"api key is not supported for provider: {provider}")

    delete_secret(API_KEY_PROVIDERS[provider])

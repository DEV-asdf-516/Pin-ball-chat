import json
import logging
import os
import stat
import tempfile
from pathlib import Path

from core.db import DATA_ROOT


log = logging.getLogger(__name__)

_SECRETS_DIRECTORY_MODE = 0o700
_SECRETS_FILE_MODE = 0o600
_SECRETS_FILE_NAME = "provider_keys.json"


def _secrets_directory() -> Path:
    return DATA_ROOT / "secrets"


def read_secrets() -> dict[str, str]:
    path: Path = _secrets_directory() / _SECRETS_FILE_NAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        log.warning("provider secrets file contains invalid JSON")
        return {}
    except OSError:
        log.warning("provider secrets file could not be read")
        return {}

    if not isinstance(raw, dict):
        log.warning("provider secrets file must contain a JSON object")
        return {}

    secrets: dict[str, str] = {}
    for name, value in raw.items():
        if not isinstance(name, str) or not isinstance(value, str):
            continue
        cleaned = value.strip()
        if cleaned:
            secrets[name] = cleaned

    return secrets


def _prepare_secrets_directory() -> Path:
    directory = _secrets_directory()
    directory.mkdir(parents=True, exist_ok=True, mode=_SECRETS_DIRECTORY_MODE)
    if stat.S_IMODE(directory.stat().st_mode) != _SECRETS_DIRECTORY_MODE:
        directory.chmod(_SECRETS_DIRECTORY_MODE)
    return directory


def _write_secrets(secrets: dict[str, str]) -> None:
    # 쓰기는 단일 uvicorn 워커 전제다. 멀티 워커 도입 시 프로세스 간 lock이 필요하다.
    directory = _prepare_secrets_directory()
    path = directory / _SECRETS_FILE_NAME
    temp_fd, temp_name = tempfile.mkstemp(dir=directory)

    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8") as output_file:
            json.dump(secrets, output_file, ensure_ascii=False, separators=(",", ":"))
            output_file.flush()
            os.fsync(output_file.fileno())
        os.replace(temp_name, path)
        path.chmod(_SECRETS_FILE_MODE)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def write_secret(name: str, value: str) -> None:
    secrets = read_secrets()
    secrets[name] = value
    _write_secrets(secrets)


def delete_secret(name: str) -> None:
    secrets = read_secrets()
    secrets.pop(name, None)
    _write_secrets(secrets)

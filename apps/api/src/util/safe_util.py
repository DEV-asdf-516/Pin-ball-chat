import json


def parse_json_dict(value: object) -> dict | None:
    try:
        parsed: object = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def get_safe_str(source: dict, key: str) -> str:
    return source.get(key) or ""


def has_str_field(source: dict, key: str) -> bool:
    return isinstance(source.get(key), str)


def get_safe_dict(source: dict, key: str) -> dict:
    value = source.get(key)
    return value if isinstance(value, dict) else {}


def get_safe_list(source: dict, key: str) -> list:
    return source.get(key) or []


def get_safe_tuple(source: dict, key: str) -> tuple:
    return source.get(key) or ()

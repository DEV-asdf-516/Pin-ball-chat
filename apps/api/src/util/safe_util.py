def get_safe_dict(source: dict, key: str) -> dict:
    return source.get(key) or {}


def get_safe_list(source: dict, key: str) -> list:
    return source.get(key) or []


def get_safe_tuple(source: dict, key: str) -> tuple:
    return source.get(key) or ()

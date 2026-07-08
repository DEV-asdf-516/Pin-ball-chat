import re

_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


def strip_from(text: str, index: int) -> str:
    return text[index:].strip()


def join_columns(columns: tuple[str, ...]) -> str:
    return ",".join(columns)


def camel_to_snake(name: str) -> str:
    return _CAMEL_BOUNDARY.sub("_", name).lower()

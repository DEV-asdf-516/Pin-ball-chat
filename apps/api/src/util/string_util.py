def strip_from(text: str, index: int) -> str:
    return text[index:].strip()


def join_columns(columns: tuple[str, ...]) -> str:
    return ",".join(columns)

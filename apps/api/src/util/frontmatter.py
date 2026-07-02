from util.string_util import strip_from

_NEWLINE: str = "\n"
_DELIMITER: str = "---"
_OPEN: str = f"{_DELIMITER}{_NEWLINE}"
_CLOSE: str = f"{_NEWLINE}{_DELIMITER}"
_LIST_PREFIX: str = "  - "


def render_frontmatter(meta: dict, body: str) -> str:
    lines: list[str] = [_DELIMITER]
    
    for key, value in meta.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            lines.extend(f"{_LIST_PREFIX}{item}" for item in value)
        else:
            lines.append(f"{key}: {value}")
    
    lines.append(_DELIMITER)
    
    return _NEWLINE.join(lines) + _NEWLINE + body.strip() + _NEWLINE


def parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith(_OPEN):
        raise ValueError("missing frontmatter")
    
    end: int = text.find(_CLOSE, len(_OPEN))

    if end == -1:
        raise ValueError("unterminated frontmatter")

    meta: dict = {}

    current: str | None = None
    
    for raw in text[len(_OPEN):end].splitlines():
        if not raw.strip():
            continue

        if raw.startswith(_LIST_PREFIX) and current:
            meta.setdefault(current, []).append(strip_from(raw, len(_LIST_PREFIX)))
            continue
        
        key, sep, value = raw.partition(":")
        
        if not sep:
            raise ValueError(f"bad frontmatter line: {raw}")
        
        current = key.strip()
        value = value.strip()
        meta[current] = [] if value == "" else value
    
    return meta, strip_from(text, end + len(_CLOSE) + 1)

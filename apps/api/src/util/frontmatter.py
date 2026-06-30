def parse_frontmatter(text):
    if not text.startswith("---\n"):
        raise ValueError("missing frontmatter")
    end = text.find("\n---", 4)
    if end == -1:
        raise ValueError("unterminated frontmatter")
    meta = {}
    current = None
    for raw in text[4:end].splitlines():
        if not raw.strip():
            continue
        if raw.startswith("  - ") and current:
            meta.setdefault(current, []).append(raw[4:].strip())
            continue
        key, sep, value = raw.partition(":")
        if not sep:
            raise ValueError(f"bad frontmatter line: {raw}")
        current = key.strip()
        value = value.strip()
        meta[current] = [] if value == "" else value
    return meta, text[end + 5 :].strip()

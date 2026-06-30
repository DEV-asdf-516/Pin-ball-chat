import json

from util.frontmatter import parse_frontmatter


def load_content_file(path):
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        data = json.loads(text)
        return data, text, "json"
    meta, body = parse_frontmatter(text)
    data = dict(meta)
    data["sourceText"] = body
    return data, body, "md"

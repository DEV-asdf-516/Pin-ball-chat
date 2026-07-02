import json
from dataclasses import dataclass
from pathlib import Path

from util.frontmatter import parse_frontmatter, render_frontmatter


@dataclass(frozen=True)
class LoadedContent:
    data: dict
    source_text: str
    source_format: str


def load_content_file(path: Path) -> LoadedContent:
    text: str = path.read_text(encoding="utf-8")

    if path.suffix == ".json":
        data: dict = json.loads(text)
        return LoadedContent(data=data, source_text=text, source_format="json")

    meta, body = parse_frontmatter(text)

    data: dict = dict(meta)
    data["sourceText"] = body

    return LoadedContent(data=data, source_text=body, source_format="md")


def write_content_file(path: Path, data: dict, source_format: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)

    if source_format == "json":
        text: str = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        path.write_text(text, encoding="utf-8")
        return text

    meta: dict = {k: v for k, v in data.items() if k != "sourceText"}

    body: str = data.get("sourceText", "")

    rendered_text : str = render_frontmatter(meta, body)
    
    path.write_text(rendered_text, encoding="utf-8")

    return body

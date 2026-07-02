import sqlite3
from pathlib import Path

from domain.content.reader import content_exists
from domain.content.specs import CONTENT_SPECS, ContentKind, ContentPayload, PlotData, parse_content_data
from domain.content.writer import upsert_content_item
from util.content_file_util import LoadedContent, load_content_file


def _is_known(conn: sqlite3.Connection, kind: ContentKind, item_id: str, loaded: dict[ContentKind, set]) -> bool:
    """이번 import 실행에서 방금 로드됐거나, 이전 실행 때 이미 DB에 있으면 True."""
    return item_id in loaded[kind] or content_exists(conn, kind, item_id)


def import_content_catalog(conn: sqlite3.Connection, root: Path) -> list[str]:
    errors: list[str] = []
    loaded: dict[ContentKind, set] = {spec.kind: set() for spec in CONTENT_SPECS}
    pending_plots: list[tuple[PlotData, LoadedContent]] = []

    for spec in CONTENT_SPECS:
        for path in sorted((root / spec.dirname).glob("*")):
            if path.suffix not in (".json", ".md"):
                continue
            try:
                content: LoadedContent = load_content_file(path)
                raw: dict = content.data

                if raw.get("type", spec.kind) != spec.kind:
                    raise ValueError(f"type must be {spec.kind}")

                payload: ContentPayload = parse_content_data(spec.kind, raw)

                if spec.kind == ContentKind.PLOT:
                    pending_plots.append((payload, content))
                    continue

                upsert_content_item(conn, spec.kind, payload, content)
                loaded[spec.kind].add(payload.id)
            except Exception as exc:
                errors.append(f"{path}: {exc}")

    for payload, content in pending_plots:
        try:
            if not _is_known(conn, ContentKind.CHARACTER, payload.characterId, loaded):
                raise ValueError(f"unknown characterId {payload.characterId}")

            if not _is_known(conn, ContentKind.USER_PROFILE, payload.userProfileId, loaded):
                raise ValueError(f"unknown userProfileId {payload.userProfileId}")

            upsert_content_item(conn, ContentKind.PLOT, payload, content)
            loaded[ContentKind.PLOT].add(payload.id)
        except Exception as exc:
            errors.append(f"plot {payload.id}: {exc}")

    return errors

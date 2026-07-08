import sqlite3
from pathlib import Path

from domain.catalog.reader import catalog_exists
from domain.catalog.specs import CATALOG_SPECS, FORWARD_REFS, CatalogKind, CatalogPayload, parse_catalog_data
from domain.catalog.writer import upsert_catalog_item
from util.catalog_util import LoadedCatalog, load_catalog_file
from util.safe_util import get_safe_tuple


def _is_known(conn: sqlite3.Connection, kind: CatalogKind, item_id: str, loaded: dict[CatalogKind, set]) -> bool:
    """이번 import 실행에서 방금 로드됐거나, 이전 실행 때 이미 DB에 있으면 True."""
    return item_id in loaded[kind] or catalog_exists(conn, kind, item_id)


def import_catalog(conn: sqlite3.Connection, root: Path) -> list[str]:
    errors: list[str] = []
    loaded: dict[CatalogKind, set] = {spec.kind: set() for spec in CATALOG_SPECS}
    pending: list[tuple[CatalogKind, CatalogPayload, LoadedCatalog]] = []

    for spec in CATALOG_SPECS:
        for path in sorted((root / spec.dirname).glob("*")):
            if path.suffix not in (".json", ".md"):
                continue
            try:
                catalog: LoadedCatalog = load_catalog_file(path)
                raw: dict = catalog.data

                if raw.get("type", spec.kind) != spec.kind:
                    raise ValueError(f"type must be {spec.kind}")

                payload: CatalogPayload = parse_catalog_data(spec.kind, raw)

                if get_safe_tuple(FORWARD_REFS, spec.kind):
                    pending.append((spec.kind, payload, catalog))
                    continue

                upsert_catalog_item(conn, spec.kind, payload, catalog)
                loaded[spec.kind].add(payload.id)
            except Exception as exc:
                errors.append(f"{path}: {exc}")

    for kind, payload, catalog in pending:
        try:
            for ref_kind, attr in FORWARD_REFS[kind]:
                ref_id = getattr(payload, attr)
                if not _is_known(conn, ref_kind, ref_id, loaded):
                    raise ValueError(f"unknown {attr} {ref_id}")

            upsert_catalog_item(conn, kind, payload, catalog)
            loaded[kind].add(payload.id)
        except Exception as exc:
            errors.append(f"{kind} {payload.id}: {exc}")

    return errors

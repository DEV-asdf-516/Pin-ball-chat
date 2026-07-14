import json
import re
import sqlite3
from pathlib import Path

from core.db import ROOT, Bind, WriteQuery, delete, upsert
from core.errors import ensure
from domain.catalog.reader import is_catalog_exists, find_catalog_by_id
from domain.catalog.specs import FORWARD_REFS, REFERENCED_BY, SPEC_BY_KIND, CatalogKind, CatalogPayload, CatalogSpec, parse_catalog_data
from util.catalog_util import LoadedCatalog, write_catalog_file
from util.safe_util import get_safe_tuple
from util.time_util import utc_now_string

_SAFE_ID = re.compile(r"^[A-Za-z0-9_\-]+$")


def _validate_id(item_id: str) -> None:
    if not _SAFE_ID.match(item_id):
        raise ValueError(f"invalid id: {item_id}")


def _file_path(kind: CatalogKind, item_id: str, root: Path) -> Path:
    spec: CatalogSpec = SPEC_BY_KIND[kind]
    return root / spec.dirname / f"{item_id}.{spec.source_format}"


def upsert_catalog_item(conn: sqlite3.Connection, kind: CatalogKind, payload: CatalogPayload, catalog: LoadedCatalog) -> None:
    # 단일 콘텐츠 항목을 DB에 upsert한다. importer.py(대량 로드)와 이 파일의 CRUD 함수들이 공유하는 저수준 프리미티브.
    spec: CatalogSpec = SPEC_BY_KIND[kind]
    ts: str = utc_now_string()

    values: Bind = Bind({
        "id": payload.id,
        **payload.columns,
        payload.json_column: json.dumps(catalog.data, ensure_ascii=False),
        "source_format": catalog.source_format,
        "source_text": catalog.source_text,
        "created_at": ts,
        "updated_at": ts,
    })

    upsert(conn, spec, values)

def create_catalog_item(conn: sqlite3.Connection, kind: CatalogKind, data: dict, root: Path = ROOT) -> dict:
    if data.get("type", kind) != kind:
        raise ValueError(f"type must be {kind}")
    
    if "id" not in data:
        raise ValueError("id is required")
    
    row_id: str = data["id"]
    
    _validate_id(row_id)
    
    path: Path = _file_path(kind, row_id, root)
    
    if path.exists():
        raise ValueError(f"{kind} {row_id} already exists")

    payload: CatalogPayload = parse_catalog_data(kind, data)

    for ref_kind, attr in get_safe_tuple(FORWARD_REFS, kind):
        ref_id = getattr(payload, attr)
        if not is_catalog_exists(conn, ref_kind, ref_id):
            raise ValueError(f"unknown {attr} {ref_id}")

    source_format: str = SPEC_BY_KIND[kind].source_format
    source_text: str = write_catalog_file(path, data, source_format)
    catalog: LoadedCatalog = LoadedCatalog(data=data, source_text=source_text, source_format=source_format)

    try:
        upsert_catalog_item(conn, kind, payload, catalog)
    except Exception:
        # DB 반영이 실패하면 방금 만든 파일도 지워서 파일/DB가 어긋나지 않게 한다.
        path.unlink(missing_ok=True)
        raise

    return find_catalog_by_id(conn, kind, row_id)


def update_catalog_item(conn: sqlite3.Connection, kind: CatalogKind, item_id: str, data: dict, root: Path = ROOT) -> dict:
    _validate_id(item_id)

    data = {**data, "id": item_id}

    if data.get("type", kind) != kind:
        raise ValueError(f"type must be {kind}")

    path: Path = _file_path(kind, item_id, root)

    item_found: bool = path.exists()
    ensure(item_found, f"{kind} {item_id} not found")

    previous_text: str = path.read_text(encoding="utf-8")

    payload: CatalogPayload = parse_catalog_data(kind, data)

    for ref_kind, attr in get_safe_tuple(FORWARD_REFS, kind):
        ref_id = getattr(payload, attr)
        if not is_catalog_exists(conn, ref_kind, ref_id):
            raise ValueError(f"unknown {attr} {ref_id}")

    source_format: str = SPEC_BY_KIND[kind].source_format
    source_text: str = write_catalog_file(path, data, source_format)
    catalog: LoadedCatalog = LoadedCatalog(data=data, source_text=source_text, source_format=source_format)

    try:
        upsert_catalog_item(conn, kind, payload, catalog)
    except Exception:
        # DB 반영이 실패하면 파일을 수정 전 내용으로 되돌린다.
        path.write_text(previous_text, encoding="utf-8")
        raise

    return find_catalog_by_id(conn, kind, item_id)


def delete_catalog_item(conn: sqlite3.Connection, kind: CatalogKind, item_id: str, root: Path = ROOT) -> dict:
    _validate_id(item_id)
    spec: CatalogSpec = SPEC_BY_KIND[kind]
    path: Path = _file_path(kind, item_id, root)

    item_found: bool = is_catalog_exists(conn, kind, item_id)
    ensure(item_found, f"{kind} {item_id} not found")

    for ref_kind, ref_column in get_safe_tuple(REFERENCED_BY, kind):
        if is_catalog_exists(conn, ref_kind, item_id, column=ref_column):
            raise ValueError(f"{kind} {item_id} is referenced by an existing {ref_kind}")

    delete(conn, WriteQuery.by_id(spec, item_id))
    
    if path.exists():
        path.unlink()
    
    return {"id": item_id, "deleted": True}

import json
import re
import sqlite3
from pathlib import Path

from core.db import ROOT
from core.errors import NotFound
from domain.content.reader import content_exists, find_content_by_id
from domain.content.specs import KIND_DIR, KIND_TABLE, TABLE_COLUMNS, ContentKind, ContentPayload, parse_content_data
from util.content_file_util import LoadedContent, write_content_file
from util.string_util import join_columns
from util.time_util import utc_now_string

_SAFE_ID = re.compile(r"^[A-Za-z0-9_\-]+$")


def upsert_content_item(conn: sqlite3.Connection, kind: ContentKind, payload: ContentPayload, content: LoadedContent) -> None:
    """단일 콘텐츠 항목을 DB에 upsert한다. importer.py(대량 로드)와 이 파일의 CRUD 함수들이 공유하는 저수준 프리미티브."""
    table: str = KIND_TABLE[kind]
    ts: str = utc_now_string()
    columns: tuple[str, ...] = TABLE_COLUMNS[table]

    values: tuple = (
        payload.id,
        payload.label,
        *payload.extra_columns,
        json.dumps(content.data, ensure_ascii=False),
        content.source_format,
        content.source_text,
        ts,
        ts
    )

    placeholders: str = ",".join("?" for _ in values)

    update_cols: list[str] = [c for c in columns if c not in ("id", "created_at")]

    updates: str = ",".join(f"{c}=excluded.{c}" for c in update_cols)

    conn.execute(
        f"INSERT INTO {table} ({join_columns(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT(id) DO UPDATE SET {updates}",
        values,
    )


def _validate_id(item_id: str) -> None:
    if not _SAFE_ID.match(item_id):
        raise ValueError(f"invalid id: {item_id}")


def _file_path(kind: ContentKind, item_id: str, root: Path) -> Path:
    ext: str = "json" if kind == ContentKind.PREFERENCE else "md"
    return root / KIND_DIR[kind] / f"{item_id}.{ext}"


def _validate_references(conn: sqlite3.Connection, kind: ContentKind, data: dict) -> None:
    if kind != ContentKind.PLOT:
        return

    payload: ContentPayload = parse_content_data(kind, data)

    if not content_exists(conn, ContentKind.CHARACTER, payload.characterId):
        raise ValueError(f"unknown characterId {payload.characterId}")

    if not content_exists(conn, ContentKind.USER_PROFILE, payload.userProfileId):
        raise ValueError(f"unknown userProfileId {payload.userProfileId}")


def _upsert_row(conn: sqlite3.Connection, kind: ContentKind, content: LoadedContent) -> None:
    payload: ContentPayload = parse_content_data(kind, content.data)
    upsert_content_item(conn, kind, payload, content)


def create_content_item(conn: sqlite3.Connection, kind: ContentKind, data: dict, root: Path = ROOT) -> dict:
    if data.get("type", kind) != kind:
        raise ValueError(f"type must be {kind}")
    
    if "id" not in data:
        raise ValueError("id is required")
    
    row_id: str = data["id"]
    
    _validate_id(row_id)
    
    path: Path = _file_path(kind, row_id, root)
    
    if path.exists():
        raise ValueError(f"{kind} {row_id} already exists")
    
    _validate_references(conn, kind, data)
    
    source_format: str = "json" if kind == ContentKind.PREFERENCE else "md"
    source_text: str = write_content_file(path, data, source_format)
    content: LoadedContent = LoadedContent(data=data, source_text=source_text, source_format=source_format)
    
    _upsert_row(conn, kind, content)
    
    return find_content_by_id(conn, kind, row_id)


def update_content_item(conn: sqlite3.Connection, kind: ContentKind, item_id: str, data: dict, root: Path = ROOT) -> dict:
    _validate_id(item_id)
    
    data = {**data, "id": item_id}
    
    if data.get("type", kind) != kind:
        raise ValueError(f"type must be {kind}")
    
    path: Path = _file_path(kind, item_id, root)
    
    if not path.exists():
        raise NotFound(f"{kind} {item_id} not found")
    
    _validate_references(conn, kind, data)
    
    source_format: str = "json" if kind == ContentKind.PREFERENCE else "md"
    source_text: str = write_content_file(path, data, source_format)
    content: LoadedContent = LoadedContent(data=data, source_text=source_text, source_format=source_format)
    
    _upsert_row(conn, kind, content)
    
    return find_content_by_id(conn, kind, item_id)


def delete_content_item(conn: sqlite3.Connection, kind: ContentKind, item_id: str, root: Path = ROOT) -> dict:
    _validate_id(item_id)
    table: str = KIND_TABLE[kind]
    path: Path = _file_path(kind, item_id, root)
    
    if not content_exists(conn, kind, item_id):
        raise NotFound(f"{kind} {item_id} not found")

    if kind == ContentKind.CHARACTER and content_exists(conn, ContentKind.PLOT, item_id, column="character_id"):
        raise ValueError(f"character {item_id} is referenced by an existing plot")

    if kind == ContentKind.USER_PROFILE and content_exists(conn, ContentKind.PLOT, item_id, column="user_profile_id"):
        raise ValueError(f"user_profile {item_id} is referenced by an existing plot")
    
    conn.execute(f"DELETE FROM {table} WHERE id=?", (item_id,))
    
    if path.exists():
        path.unlink()
    
    return {"id": item_id, "deleted": True}

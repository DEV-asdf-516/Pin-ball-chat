import json
import sqlite3
from pathlib import Path

from core.db import DATA_ROOT
from core.errors import ensure
from domain.catalog.reader import find_catalog_by_id
from domain.catalog.specs import SPEC_BY_KIND, CatalogKind, CatalogSpec
from domain.catalog.writer import update_catalog_item
from util.time_util import utc_now_string

_AVATAR_EXTENSIONS: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}
_MAX_AVATAR_BYTES: int = 10 * 1024 * 1024


def save_avatar(conn: sqlite3.Connection, kind: CatalogKind, item_id: str, content: bytes, content_type: str, root: Path = DATA_ROOT) -> dict:
    ext: str | None = _AVATAR_EXTENSIONS.get(content_type)

    if not ext:
        raise ValueError(f"unsupported image type: {content_type}")

    if len(content) > _MAX_AVATAR_BYTES:
        raise ValueError("image too large (max 10MB)")

    existing: dict | None = find_catalog_by_id(conn, kind, item_id)
    ensure(existing, f"{kind} {item_id} not found")

    spec: CatalogSpec = SPEC_BY_KIND[kind]
    avatar_dir: Path = root / "uploads" / spec.dirname
    avatar_dir.mkdir(parents=True, exist_ok=True)

    # 확장자가 바뀌는 재업로드에 대비해 이 item의 이전 아바타 파일들을 정리한다.
    for stale in avatar_dir.glob(f"{item_id}.*"):
        stale.unlink()

    (avatar_dir / f"{item_id}.{ext}").write_bytes(content)

    json_column: str = next(c for c in spec.columns if c.endswith("_json"))
    data: dict = json.loads(existing[json_column])
    data["avatarUrl"] = f"/uploads/{spec.dirname}/{item_id}.{ext}?v={utc_now_string()}"

    return update_catalog_item(conn, kind, item_id, data, root=root)

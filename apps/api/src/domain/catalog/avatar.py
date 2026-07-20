import hashlib
import io
import json
import sqlite3
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from core.db import DATA_ROOT
from core.errors import ensure
from domain.catalog.reader import find_catalog_by_id
from domain.catalog.specs import SPEC_BY_KIND, CatalogKind, CatalogSpec
from domain.catalog.writer import update_catalog_item

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

# 브라우저가 그대로 표시할 수 있는 포맷. 그 외(HEIC 등)는 WebP로 변환해 저장한다.
_NATIVE_FORMATS: dict[str, str] = {
    "PNG": "png",
    "JPEG": "jpg",
    "WEBP": "webp",
    "GIF": "gif",
}
_MAX_AVATAR_BYTES: int = 10 * 1024 * 1024


def _normalize_image(content: bytes, content_type: str) -> tuple[bytes, str]:
    try:
        image = Image.open(io.BytesIO(content))
        image_format: str | None = image.format
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"unsupported image type: {content_type}") from exc

    if image_format in _NATIVE_FORMATS:
        return content, _NATIVE_FORMATS[image_format]

    try:
        image = ImageOps.exif_transpose(image)
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
        buffer = io.BytesIO()
        image.save(buffer, format="WEBP", quality=90)
    except Exception as exc:
        raise ValueError(f"unsupported image type: {content_type}") from exc

    return buffer.getvalue(), "webp"


def save_avatar(conn: sqlite3.Connection, kind: CatalogKind, item_id: str, content: bytes, content_type: str, root: Path = DATA_ROOT) -> dict:
    if len(content) > _MAX_AVATAR_BYTES:
        raise ValueError("image too large (max 10MB)")

    content, ext = _normalize_image(content, content_type)

    existing: dict | None = find_catalog_by_id(conn, kind, item_id)
    ensure(existing, f"{kind} {item_id} not found")

    spec: CatalogSpec = SPEC_BY_KIND[kind]
    avatar_dir: Path = root / "uploads" / spec.dirname
    avatar_dir.mkdir(parents=True, exist_ok=True)

    # 확장자가 바뀌는 재업로드에 대비해 이 item의 이전 아바타 파일들을 정리한다.
    for stale in avatar_dir.glob(f"{item_id}.*"):
        stale.unlink()

    (avatar_dir / f"{item_id}.{ext}").write_bytes(content)

    # 콘텐츠 해시를 캐시 버전으로 사용해 같은 초에 교체해도 URL이 달라지게 한다.
    version: str = hashlib.sha256(content).hexdigest()[:12]

    json_column: str = next(c for c in spec.columns if c.endswith("_json"))
    data: dict = json.loads(existing[json_column])
    data["avatarUrl"] = f"/uploads/{spec.dirname}/{item_id}.{ext}?v={version}"

    return update_catalog_item(conn, kind, item_id, data, root=root)

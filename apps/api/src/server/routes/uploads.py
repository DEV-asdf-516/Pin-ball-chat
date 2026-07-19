from fastapi import APIRouter, File, UploadFile

from domain.catalog.specs import CatalogKind
from domain.catalog.avatar import save_avatar
from server.dependencies import DbConn

router = APIRouter()


@router.post("/api/uploads/{kind}/{item_id}")
async def post_avatar(kind: CatalogKind, item_id: str, conn: DbConn, file: UploadFile = File(...)):
    content: bytes = await file.read()
    return save_avatar(conn, kind, item_id, content, file.content_type)

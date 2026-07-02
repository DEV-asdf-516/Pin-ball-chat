from fastapi import APIRouter

from domain.characters import get_character
from domain.content.reader import find_all_content
from domain.content.specs import ContentKind
from domain.content.writer import create_content_item, delete_content_item, update_content_item
from server.dependencies import DbConn
from server.schemas import CharacterCreateRequest, CharacterUpdateRequest

router = APIRouter()


@router.get("/api/characters")
def get_characters(conn: DbConn):
    return find_all_content(conn, ContentKind.CHARACTER)


@router.get("/api/characters/{character_id}")
def get_character_route(character_id: str, conn: DbConn):
    return get_character(conn, character_id)


@router.post("/api/characters")
def post_character(conn: DbConn, body: CharacterCreateRequest):
    return create_content_item(conn, ContentKind.CHARACTER, body.to_dict())


@router.put("/api/characters/{character_id}")
def put_character(character_id: str, conn: DbConn, body: CharacterUpdateRequest):
    return update_content_item(conn, ContentKind.CHARACTER, character_id, body.to_dict())


@router.delete("/api/characters/{character_id}")
def delete_character(character_id: str, conn: DbConn):
    return delete_content_item(conn, ContentKind.CHARACTER, character_id)

from fastapi import APIRouter

from domain.characters import get_character
from domain.catalog.reader import list_catalog_by_kind
from domain.catalog.specs import CatalogKind
from domain.catalog.writer import create_catalog_item, delete_catalog_item, update_catalog_item
from server.dependencies import DbConn
from server.specs import CharacterCreateRequest, CharacterResponse, CharactersPageResponse, CharacterUpdateRequest, CatalogDeleteResponse

router = APIRouter()


@router.get("/api/characters", response_model=CharactersPageResponse)
def get_characters(conn: DbConn, before: int | None = None, limit: int = 100):
    page = list_catalog_by_kind(conn, CatalogKind.CHARACTER, before, limit)
    return {
        "characters": page["items"], 
        "nextCursor": page["nextCursor"], 
        "hasMore": page["hasMore"]
     }


@router.get("/api/characters/{character_id}", response_model=CharacterResponse)
def get_character_route(character_id: str, conn: DbConn):
    return get_character(conn, character_id)


@router.post("/api/characters", response_model=CharacterResponse)
def post_character(conn: DbConn, body: CharacterCreateRequest):
    return create_catalog_item(conn, CatalogKind.CHARACTER, body.to_dict())


@router.put("/api/characters/{character_id}", response_model=CharacterResponse)
def put_character(character_id: str, conn: DbConn, body: CharacterUpdateRequest):
    return update_catalog_item(conn, CatalogKind.CHARACTER, character_id, body.to_dict())


@router.delete("/api/characters/{character_id}", response_model=CatalogDeleteResponse)
def delete_character(character_id: str, conn: DbConn):
    return delete_catalog_item(conn, CatalogKind.CHARACTER, character_id)

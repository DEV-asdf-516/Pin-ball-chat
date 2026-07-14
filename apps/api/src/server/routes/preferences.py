from fastapi import APIRouter

from domain.catalog.reader import list_catalog_by_kind
from domain.catalog.specs import CatalogKind
from domain.catalog.writer import create_catalog_item, delete_catalog_item, update_catalog_item
from server.dependencies import DbConn
from server.specs import CatalogDeleteResponse, PreferenceCreateRequest, PreferenceProfilesPageResponse, PreferenceResponse, PreferenceUpdateRequest

router = APIRouter()


@router.get("/api/preference-profiles", response_model=PreferenceProfilesPageResponse)
def get_preference_profiles(conn: DbConn, before: int | None = None, limit: int = 100):
    page = list_catalog_by_kind(conn, CatalogKind.PREFERENCE, before, limit)
    return {
        "preference_profiles": page["items"], 
        "nextCursor": page["nextCursor"], 
        "hasMore": page["hasMore"]
        }


@router.post("/api/preference-profiles", response_model=PreferenceResponse)
def post_preference_profile(conn: DbConn, body: PreferenceCreateRequest):
    return create_catalog_item(conn, CatalogKind.PREFERENCE, body.to_dict())


@router.put("/api/preference-profiles/{preference_id}", response_model=PreferenceResponse)
def put_preference_profile(preference_id: str, conn: DbConn, body: PreferenceUpdateRequest):
    return update_catalog_item(conn, CatalogKind.PREFERENCE, preference_id, body.to_dict())


@router.delete("/api/preference-profiles/{preference_id}", response_model=CatalogDeleteResponse)
def delete_preference_profile(preference_id: str, conn: DbConn):
    return delete_catalog_item(conn, CatalogKind.PREFERENCE, preference_id)

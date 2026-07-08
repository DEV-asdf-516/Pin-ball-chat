from fastapi import APIRouter

from domain.catalog.reader import find_all_by_kind
from domain.catalog.specs import CatalogKind
from domain.user_profiles import get_user_profile
from domain.catalog.writer import create_catalog_item, delete_catalog_item, update_catalog_item
from server.dependencies import DbConn
from server.specs import CatalogDeleteResponse, UserProfileCreateRequest, UserProfileResponse, UserProfileUpdateRequest

router = APIRouter()


@router.get("/api/user-profiles", response_model=list[UserProfileResponse])
def get_user_profiles(conn: DbConn):
    return find_all_by_kind(conn, CatalogKind.USER_PROFILE)


@router.get("/api/user-profiles/{user_profile_id}", response_model=UserProfileResponse)
def get_user_profile_route(user_profile_id: str, conn: DbConn):
    return get_user_profile(conn, user_profile_id)


@router.post("/api/user-profiles", response_model=UserProfileResponse)
def post_user_profile(conn: DbConn, body: UserProfileCreateRequest):
    return create_catalog_item(conn, CatalogKind.USER_PROFILE, body.to_dict())


@router.put("/api/user-profiles/{user_profile_id}", response_model=UserProfileResponse)
def put_user_profile(user_profile_id: str, conn: DbConn, body: UserProfileUpdateRequest):
    return update_catalog_item(conn, CatalogKind.USER_PROFILE, user_profile_id, body.to_dict())


@router.delete("/api/user-profiles/{user_profile_id}", response_model=CatalogDeleteResponse)
def delete_user_profile(user_profile_id: str, conn: DbConn):
    return delete_catalog_item(conn, CatalogKind.USER_PROFILE, user_profile_id)

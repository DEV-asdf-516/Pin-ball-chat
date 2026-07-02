from fastapi import APIRouter

from domain.content.reader import find_all_content
from domain.content.specs import ContentKind
from domain.user_profiles import get_user_profile
from domain.content.writer import create_content_item, delete_content_item, update_content_item
from server.dependencies import DbConn
from server.schemas import UserProfileCreateRequest, UserProfileUpdateRequest

router = APIRouter()


@router.get("/api/user-profiles")
def get_user_profiles(conn: DbConn):
    return find_all_content(conn, ContentKind.USER_PROFILE)


@router.get("/api/user-profiles/{user_profile_id}")
def get_user_profile_route(user_profile_id: str, conn: DbConn):
    return get_user_profile(conn, user_profile_id)


@router.post("/api/user-profiles")
def post_user_profile(conn: DbConn, body: UserProfileCreateRequest):
    return create_content_item(conn, ContentKind.USER_PROFILE, body.to_dict())


@router.put("/api/user-profiles/{user_profile_id}")
def put_user_profile(user_profile_id: str, conn: DbConn, body: UserProfileUpdateRequest):
    return update_content_item(conn, ContentKind.USER_PROFILE, user_profile_id, body.to_dict())


@router.delete("/api/user-profiles/{user_profile_id}")
def delete_user_profile(user_profile_id: str, conn: DbConn):
    return delete_content_item(conn, ContentKind.USER_PROFILE, user_profile_id)

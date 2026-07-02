from fastapi import APIRouter

from domain.content.reader import find_all_content
from domain.content.specs import ContentKind
from domain.content.writer import create_content_item, delete_content_item, update_content_item
from server.dependencies import DbConn
from server.schemas import PreferenceCreateRequest, PreferenceUpdateRequest

router = APIRouter()


@router.get("/api/preference-profiles")
def get_preference_profiles(conn: DbConn):
    return find_all_content(conn, ContentKind.PREFERENCE)


@router.post("/api/preference-profiles")
def post_preference_profile(conn: DbConn, body: PreferenceCreateRequest):
    return create_content_item(conn, ContentKind.PREFERENCE, body.to_dict())


@router.put("/api/preference-profiles/{preference_id}")
def put_preference_profile(preference_id: str, conn: DbConn, body: PreferenceUpdateRequest):
    return update_content_item(conn, ContentKind.PREFERENCE, preference_id, body.to_dict())


@router.delete("/api/preference-profiles/{preference_id}")
def delete_preference_profile(preference_id: str, conn: DbConn):
    return delete_content_item(conn, ContentKind.PREFERENCE, preference_id)

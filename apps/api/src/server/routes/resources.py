from fastapi import APIRouter

from core.db import rows
from server.routes._helpers import db_business, one
from server.schemas import HealthResponse


router = APIRouter()


@router.get("/api/health", response_model=HealthResponse)
def health():
    return {"ok": True}


@router.get("/api/characters")
def list_characters():
    return db_business(lambda conn: rows(conn,"characters"))


@router.get("/api/characters/{character_id}")
def get_character(character_id: str):
    return one("characters", character_id)


@router.get("/api/user-profiles")
def list_user_profiles():
    return db_business(lambda conn: rows(conn,"user_profiles"))


@router.get("/api/user-profiles/{user_profile_id}")
def get_user_profile(user_profile_id: str):
    return one("user_profiles", user_profile_id)


@router.get("/api/plots")
def list_plots():
    return db_business(lambda conn: rows(conn,"plots"))


@router.get("/api/plots/{plot_id}")
def get_plot(plot_id: str):
    return one("plots", plot_id)


@router.get("/api/preference-profiles")
def list_preference_profiles():
    return db_business(lambda conn: rows(conn,"preference_profiles"))

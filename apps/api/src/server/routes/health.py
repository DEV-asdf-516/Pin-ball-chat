from fastapi import APIRouter

from server.schemas import HealthResponse

router = APIRouter()


@router.get("/api/health", response_model=HealthResponse)
def health():
    return {"ok": True}

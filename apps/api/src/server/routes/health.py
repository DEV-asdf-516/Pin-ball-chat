from fastapi import APIRouter

from server.specs import HealthResponse

router = APIRouter()


@router.get("/api/health", response_model=HealthResponse)
def health():
    return {"ok": True}

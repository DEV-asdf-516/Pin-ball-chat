from fastapi import APIRouter

from ai.registry import list_provider_models
from server.specs import ModelsResponse

router = APIRouter()


@router.get("/api/models", response_model=ModelsResponse)
async def get_models(provider: str):
    models = await list_provider_models(provider)
    return {"provider": provider, "models": models}

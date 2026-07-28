from fastapi import APIRouter

from ai.connections import check_provider_connection, get_provider_connection, list_provider_connections, logout_provider, start_provider_login, submit_provider_login_code
from ai.specs import ProviderName
from core.errors import NotFound
from server.specs import ProviderConnectionResponse, ProviderConnectionsResponse, ProviderLoginCodeRequest, ProviderLoginResponse


router = APIRouter()


@router.get("/api/provider-connections", response_model=ProviderConnectionsResponse)
async def get_provider_connections():
    return {"providers": await list_provider_connections()}


@router.get("/api/provider-connections/{provider}", response_model=ProviderConnectionResponse)
async def get_provider_connection_route(provider: ProviderName):
    connection = await get_provider_connection(provider)
    if not connection:
        raise NotFound(f"unknown provider: {provider}")
    return connection


@router.post("/api/provider-connections/{provider}/login", response_model=ProviderLoginResponse)
async def post_provider_login(provider: ProviderName):
    return await start_provider_login(provider)


@router.post("/api/provider-connections/{provider}/login/code")
async def post_provider_login_code(provider: ProviderName, body: ProviderLoginCodeRequest):
    return await submit_provider_login_code(provider, body.code)


@router.post("/api/provider-connections/{provider}/test")
async def post_provider_connection_test(provider: ProviderName):
    return await check_provider_connection(provider)


@router.delete("/api/provider-connections/{provider}", status_code=204)
async def delete_provider_connection(provider: ProviderName):
    await logout_provider(provider)

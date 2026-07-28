import asyncio

from core.errors import Conflict
from ai.errors import ProviderConnectionBusyError, ProviderErrorCode, ProviderRuntimeError, ProviderTimeoutError
from ai.providers.base import AIProvider, LoginCapableProvider
from ai.registry import get_provider, list_provider_models
from ai.specs import ProviderConnection, ProviderName


_CONNECTABLE_PROVIDER_NAMES = ProviderName.connectable()


def _require_login_capable_provider(name: str, action: str) -> LoginCapableProvider:
    provider:AIProvider|None = get_provider(name)
    
    if not provider:
        raise ValueError(f"unknown provider: {name}")
    
    if not isinstance(provider, LoginCapableProvider):
        raise ValueError(f"{action} is not supported for provider: {name}")
    
    return provider


async def list_provider_connections() -> list[ProviderConnection]:
    return list(await asyncio.gather(*(get_provider(name).connection() for name in _CONNECTABLE_PROVIDER_NAMES)))


async def get_provider_connection(provider: str) -> ProviderConnection | None:
    if provider not in _CONNECTABLE_PROVIDER_NAMES:
        return None
    
    return await get_provider(provider).connection()


async def check_provider_connection(provider: str) -> dict:
    connection = await get_provider_connection(provider)
    
    if not connection:
        raise ValueError(f"unknown provider: {provider}")
    
    if connection.status != "connected":
        return {
            "ok": False, 
            "provider": provider, 
            "code": connection.action_required or ProviderErrorCode.PROVIDER_AUTH_REQUIRED
        }
    
    try:
        await list_provider_models(provider)
        return {
            "ok": True, 
            "provider": provider, 
            "code": None
        }
    except ProviderTimeoutError:
        return {
            "ok": False, 
            "provider": provider, 
            "code": ProviderErrorCode.PROVIDER_TIMEOUT
        }
    except ProviderRuntimeError as exc:
        return {
            "ok": False, 
            "provider": provider, 
            "code": exc.code
        }
    except Exception:
        return {
            "ok": False, 
            "provider": provider, 
            "code": ProviderErrorCode.PROVIDER_BAD_GATEWAY
        }


async def start_provider_login(provider: str) -> dict:
    result = await _require_login_capable_provider(provider, "login").start_login()
    return {
        "provider": provider,
        "verificationUrl": result.get("verificationUrl"),
        "userCode": result.get("userCode"),
        "status": result.get("status", "login_pending"),
    }


async def submit_provider_login_code(provider: str, code: str) -> dict:
    login_state = await _require_login_capable_provider(provider, "authorization code submission").submit_login_code(code)
    return {
        "provider": provider, 
        **login_state
    }


async def logout_provider(provider: str) -> None:
    try:
        await _require_login_capable_provider(provider, "logout").logout()
    except ProviderConnectionBusyError as exc:
        raise Conflict(str(exc)) from exc

from contextlib import asynccontextmanager
from typing import Callable

import httpx

from ai.errors import ProviderBadGatewayError, ProviderTimeoutError


@asynccontextmanager
async def translate_http_errors(provider_name: str, should_translate: Callable[[httpx.HTTPStatusError, str], bool] = lambda exc, body: True):
    """httpx 타임아웃/HTTPStatusError를 공통 provider 예외로 변환한다.

    should_translate이 False를 반환하면 원본 HTTPStatusError를 그대로 다시 던진다
    (ollama처럼 특정 상태 코드만 bad-gateway로 취급하고 싶은 provider를 위한 훅).
    """
    try:
        yield
    except httpx.TimeoutException as exc:
        raise ProviderTimeoutError(f"{provider_name} request timed out") from exc
    except httpx.HTTPStatusError as exc:
        await exc.response.aread()
        error_body: str = exc.response.text
        if should_translate(exc, error_body):
            raise ProviderBadGatewayError(f"{provider_name} returned {exc.response.status_code}: {error_body}") from exc
        raise

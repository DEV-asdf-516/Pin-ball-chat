import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ai.errors import EmptyOutputError, ProviderBadGatewayError, ProviderErrorCode, ProviderRuntimeError, ProviderTimeoutError
from core.errors import BadRequest, Conflict, NotFound

log = logging.getLogger(__name__)

# exception -> (HTTP status, 응답 error 코드). str(exc)를 message로 그대로 반환하는,
# 서로 매핑만 다르고 몸통이 동일한 에러들은 여기 한 줄만 추가하면 등록된다.
_SIMPLE_ERRORS: dict[type[Exception], tuple[int, str]] = {
    NotFound: (404, "not_found"),
    BadRequest: (400, "bad_request"),
    Conflict: (409, "conflict"),
    ValueError: (400, "bad_request"),
    EmptyOutputError: (502, ProviderErrorCode.PROVIDER_BAD_GATEWAY),
}


def _simple_handler(status_code: int, error_code: str):
    async def handler(_request: Request, exc: Exception):
        return JSONResponse(status_code=status_code, content={"error": error_code, "message": str(exc)})
    return handler


def register_error_handlers(app: FastAPI):
    @app.exception_handler(ProviderTimeoutError)
    async def provider_timeout(_request: Request, exc: ProviderTimeoutError):
        body : dict[str,str] = {
            "error": ProviderErrorCode.PROVIDER_TIMEOUT,
            "code": ProviderErrorCode.PROVIDER_TIMEOUT,
            "provider": exc.provider,
            "message": str(exc),
            "retryable": True
            }
        if exc.phase:
            body["phase"] = exc.phase
        return JSONResponse(status_code=504, content=body)

    @app.exception_handler(ProviderBadGatewayError)
    async def provider_bad_gateway(_request: Request, exc: ProviderBadGatewayError):
        return JSONResponse(status_code=502, content={"error": ProviderErrorCode.PROVIDER_BAD_GATEWAY, "code": ProviderErrorCode.PROVIDER_BAD_GATEWAY, "provider": exc.provider, "message": str(exc), "retryable": True})

    @app.exception_handler(ProviderRuntimeError)
    async def provider_runtime_error(_request: Request, exc: ProviderRuntimeError):
        body : dict[str,str] = {"error": exc.code, "code": exc.code, "provider": exc.provider, "message": str(exc), "retryable": exc.retryable}
        if exc.phase:
            body["phase"] = exc.phase
        return JSONResponse(status_code=502, content=body)

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {"error": "http_error", "message": str(exc.detail)}
        return JSONResponse(status_code=exc.status_code, content=detail)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"error": "validation_error", "message": "request validation failed", "details": exc.errors()})

    for exc_type, (status_code, error_code) in _SIMPLE_ERRORS.items():
        app.add_exception_handler(exc_type, _simple_handler(status_code, error_code))

    @app.exception_handler(Exception)
    async def unexpected_error(_request: Request, exc: Exception):
        log.exception("unhandled exception")
        return JSONResponse(status_code=500, content={"error": "internal_error", "message": "internal server error"})

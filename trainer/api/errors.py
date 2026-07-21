# Central exception -> HTTP response mapping, mirroring apps/api/src/server/errors.py.
# route handler는 도메인 예외를 그냥 raise하면 되고, HTTP status/응답 형태로의 변환은 여기 한 곳에서만 한다.

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ..core.errors import AppDbUnavailable, Conflict, NotFound
from ..domain.datasets import DatasetError, DatasetFormatMismatch

# 예외 타입 -> HTTP status. str(exc)가 그대로 {"error": ...} 메시지가 된다.
# 상속 관계(DatasetFormatMismatch < DatasetError)가 있어도 Starlette가 raise된 예외의 MRO를
# 순서대로 훑어 더 구체적인 타입을 먼저 찾으므로 dict 순서는 상관없다.
_SIMPLE_ERRORS: dict[type[Exception], int] = {
    DatasetFormatMismatch: 409,
    DatasetError: 400,
    FileExistsError: 409,
    Conflict: 409,
    NotFound: 404,
    AppDbUnavailable: 503,
}


def _simple_handler(status_code: int):
    async def handler(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status_code, content={"error": str(exc)})
    return handler


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_error_handler(_request: Request, exc: HTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)})

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, __: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": "invalid request"})

    for exc_type, status_code in _SIMPLE_ERRORS.items():
        app.add_exception_handler(exc_type, _simple_handler(status_code))

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ai.errors import EmptyOutputError, OllamaBadGatewayError, OllamaTimeoutError
from core.errors import BadRequest, NotFound

log = logging.getLogger(__name__)


def register_error_handlers(app: FastAPI):
    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {"error": "http_error", "message": str(exc.detail)}
        return JSONResponse(status_code=exc.status_code, content=detail)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"error": "validation_error", "message": "request validation failed", "details": exc.errors()})

    @app.exception_handler(NotFound)
    async def not_found_error(_request: Request, exc: NotFound):
        return JSONResponse(status_code=404, content={"error": "not_found", "message": str(exc)})

    @app.exception_handler(BadRequest)
    async def bad_request_error(_request: Request, exc: BadRequest):
        return JSONResponse(status_code=400, content={"error": "bad_request", "message": str(exc)})

    @app.exception_handler(ValueError)
    async def value_error(_request: Request, exc: ValueError):
        return JSONResponse(status_code=400, content={"error": "bad_request", "message": str(exc)})

    @app.exception_handler(OllamaTimeoutError)
    async def ollama_timeout_error(_request: Request, exc: OllamaTimeoutError):
        return JSONResponse(status_code=504, content={"error": "ollama_timeout", "message": str(exc)})

    @app.exception_handler(OllamaBadGatewayError)
    async def ollama_bad_gateway_error(_request: Request, exc: OllamaBadGatewayError):
        return JSONResponse(status_code=502, content={"error": "ollama_bad_gateway", "message": str(exc)})

    @app.exception_handler(EmptyOutputError)
    async def empty_output_error(_request: Request, exc: EmptyOutputError):
        return JSONResponse(status_code=502, content={"error": "empty_output", "message": str(exc)})

    @app.exception_handler(Exception)
    async def unexpected_error(_request: Request, exc: Exception):
        log.exception("unhandled exception")
        return JSONResponse(status_code=500, content={"error": "internal_error", "message": "internal server error"})

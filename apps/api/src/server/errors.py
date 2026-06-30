import traceback

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ai.errors import EmptyOutputError, OllamaBadGatewayError, OllamaTimeoutError
from core.errors import BadRequest, NotFound


def business(call):
    try:
        return call()
    except OllamaTimeoutError as exc:
        raise HTTPException(status_code=504, detail={"error": "ollama_timeout", "message": str(exc)})
    except OllamaBadGatewayError as exc:
        raise HTTPException(status_code=502, detail={"error": "ollama_bad_gateway", "message": str(exc)})
    except EmptyOutputError as exc:
        raise HTTPException(status_code=502, detail={"error": "empty_output", "message": str(exc)})
    except NotFound as exc:
        raise HTTPException(status_code=404, detail={"error": "not_found", "message": str(exc)})
    except BadRequest as exc:
        raise HTTPException(status_code=400, detail={"error": "bad_request", "message": str(exc)})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": "bad_request", "message": str(exc)})


def register_error_handlers(app: FastAPI):
    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {"error": "http_error", "message": str(exc.detail)}
        return JSONResponse(status_code=exc.status_code, content=detail)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"error": "validation_error", "message": "request validation failed", "details": exc.errors()})

    @app.exception_handler(Exception)
    async def unexpected_error(_request: Request, exc: Exception):
        traceback.print_exception(type(exc), exc, exc.__traceback__)
        return JSONResponse(status_code=500, content={"error": "internal_error", "message": "internal server error"})

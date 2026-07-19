"""FastAPI entry point for the native trainer service."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .db import initialize
from .routes_datasets import router as datasets_router
from .routes_runs import router as runs_router


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"

app = FastAPI()


@app.exception_handler(HTTPException)
async def http_error_handler(_: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, __: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": "invalid request"})


@app.on_event("startup")
def startup() -> None:
    initialize()


app.include_router(datasets_router)
app.include_router(runs_router)
app.mount("/web", StaticFiles(directory=WEB), name="web")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")

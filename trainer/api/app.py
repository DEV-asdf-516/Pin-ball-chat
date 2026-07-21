# FastAPI entry point for the native trainer service.

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..core.db import initialize
from .errors import register_error_handlers
from .routes import datasets, runs


ROOT: Path = Path(__file__).resolve().parents[1]
WEB: Path = ROOT / "web"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize()
    yield


app: FastAPI = FastAPI(lifespan=lifespan)

register_error_handlers(app)

app.include_router(datasets.router)
app.include_router(runs.router)
app.mount("/web", StaticFiles(directory=WEB), name="web")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")

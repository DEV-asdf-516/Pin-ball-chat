import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.db import ROOT, connect, init_db
from domain.content.importer import import_content_catalog
from server.errors import register_error_handlers
from server.router import register_routes

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logging.getLogger("ai.providers.ollama").setLevel(logging.DEBUG)

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    with connect() as conn:
        init_db(conn)
        errors = import_content_catalog(conn, ROOT)
        if errors:
            log.warning("content load errors:\n%s", "\n".join(errors))
    yield


def create_app():
    app = FastAPI(title="Pinballchat API", version="0.1.0", docs_url="/docs", openapi_url="/openapi.json", lifespan=lifespan)
    register_error_handlers(app)
    register_routes(app)
    return app

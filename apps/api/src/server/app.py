import logging

from fastapi import FastAPI

from core.db import connect, init_db, load_resources
from server.errors import register_error_handlers
from server.router import register_routes

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logging.getLogger("ai.providers.ollama").setLevel(logging.DEBUG)


def create_app():
    app = FastAPI(title="Pinballchat API", version="0.1.0", docs_url="/docs", openapi_url="/openapi.json")
    register_error_handlers(app)
    register_routes(app)

    @app.on_event("startup")
    def startup():
        with connect() as conn:
            init_db(conn)
            errors = load_resources(conn)
            if errors:
                print("\n".join(errors))

    return app

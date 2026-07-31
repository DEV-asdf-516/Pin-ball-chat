import asyncio
import ipaddress
import logging
import os
import re
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from ai.transport.http_client import HttpClient
from ai.runtime.codex.runtime import runtime as codex_runtime
from ai.auth import claude_auth
from ai.auth.codex_auth import shutdown_codex
from ai.errors import ProviderRuntimeError, ProviderTimeoutError
from core.db import DATA_ROOT, connect, init_db, session
from domain.catalog.importer import import_catalog
from server.errors import register_error_handlers
from server.router import register_routes

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

log = logging.getLogger(__name__)


def _csv_env(name: str, default: str) -> list[str]:
    return [value.strip() for value in os.environ.get(name, default).split(",") if value.strip()]


ALLOWED_ORIGINS = _csv_env("PINBALLCHAT_ALLOWED_ORIGINS", "http://localhost:3000")
ALLOWED_HOSTS = _csv_env("PINBALLCHAT_ALLOWED_HOSTS", "*")
LAN_ORIGIN_REGEX = r"^http://(?:localhost|127\.0\.0\.1|\[::1\]|(?:10|192\.168)(?:\.\d{1,3}){2,3}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}|[a-zA-Z0-9-]+\.local):3000$"


def _is_local_network_host(value: str) -> bool:
    hostname = urlsplit(f"//{value}").hostname
    if not hostname:
        return False
    try:
        address = ipaddress.ip_address(hostname)
        return address.is_private or address.is_loopback or address.is_link_local
    except ValueError:
        return hostname == "localhost" or hostname.endswith(".local")


def _is_local_network_origin(origin: str) -> bool:
    if not re.fullmatch(LAN_ORIGIN_REGEX, origin):
        return False
    parsed = urlsplit(origin)
    return parsed.hostname is not None and _is_local_network_host(parsed.netloc)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    with session(connect) as conn:
        init_db(conn)
        errors = import_catalog(conn, DATA_ROOT)
        if errors:
            log.warning("content load errors:\n%s", "\n".join(errors))
    try:
        # 시작 시 잔존 persisted thread 정리는 ensure_started 내부에서 수행된다.
        await codex_runtime.ensure_started()
    except ProviderRuntimeError as exc:
        log.warning("codex startup cleanup unavailable: %s", exc.code)
    except ProviderTimeoutError:
        log.warning("codex startup cleanup timed out")
    except Exception:
        log.exception("codex startup cleanup failed")
    try:
        yield
    finally:
        await asyncio.gather(claude_auth.session.shutdown(), shutdown_codex(), return_exceptions=True)
        await HttpClient().close()


def create_app():
    app = FastAPI(title="Pinballchat API", version="0.1.0", docs_url="/docs", openapi_url="/openapi.json", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_origin_regex=LAN_ORIGIN_REGEX,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def reject_untrusted_origin(request, call_next):
        
        if not _is_local_network_host(request.headers.get("host", "")):
            return JSONResponse(status_code=400, content={"error": "invalid_host", "message": "host is not allowed"})
        origin = request.headers.get("origin")
        
        is_unlisted_origin: bool = bool(origin) \
            and origin not in ALLOWED_ORIGINS \
            and not _is_local_network_origin(origin)

        if origin == "null" or is_unlisted_origin:
            return JSONResponse(status_code=403, content={"error": "forbidden_origin", "message": "origin is not allowed"})
        
        return await call_next(request)

    register_error_handlers(app)
    register_routes(app)

    uploads_dir = DATA_ROOT / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")

    return app

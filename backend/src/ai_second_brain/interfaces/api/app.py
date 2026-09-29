"""FastAPI application factory."""

import asyncio
import http
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import psycopg
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from psycopg_pool import PoolTimeout
from starlette.exceptions import HTTPException as StarletteHTTPException

from ai_second_brain.auth.sessions import SessionStore
from ai_second_brain.auth.throttle import LoginThrottle
from ai_second_brain.config import Settings, get_settings
from ai_second_brain.db import create_pool
from ai_second_brain.interfaces.api.routes import auth, health

logger = logging.getLogger("ai_second_brain.api")

PLACEHOLDER_HASH = "$argon2id$v=19$m=65536,t=3,p=4$placeholder$placeholder"

# API contract version: bumped only for breaking API changes, independent of app releases,
# so a release never makes the generated web client stale.
API_VERSION = "1.0"


def utc_now() -> datetime:
    return datetime.now(UTC)


async def _database_unavailable(request: Request, exc: Exception) -> JSONResponse:
    logger.warning("database unavailable: %s", type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "database_unavailable"})


async def _invalid_request(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": "invalid_request"})


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    exc = cast(StarletteHTTPException, exc)
    detail = exc.detail
    try:
        default_phrase = http.HTTPStatus(exc.status_code).phrase
    except ValueError:
        default_phrase = None
    if default_phrase is not None and detail == default_phrase:
        detail = default_phrase.lower().replace(" ", "_").replace("-", "_")
    return JSONResponse(
        status_code=exc.status_code, content={"detail": detail}, headers=exc.headers
    )


async def _log_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    start = time.perf_counter()
    status_code = 500  # stays 500 when the handler raises
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info("%s %s %s %.1fms", request.method, request.url.path, status_code, elapsed_ms)


def create_app(
    settings: Settings | None = None,
    *,
    clock: Callable[[], datetime] = utc_now,
    throttle_clock: Callable[[], float] = time.monotonic,
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        pool = create_pool(settings.database_url)
        await pool.open(wait=False)
        app.state.pool = pool
        app.state.sessions = SessionStore(pool, timedelta(days=settings.session_ttl_days), clock)
        try:
            await app.state.sessions.purge_expired()
        except (PoolTimeout, psycopg.Error, OSError):
            logger.warning("session purge skipped: database unavailable")
        try:
            yield
        finally:
            await pool.close(timeout=0.1)

    docs_enabled = settings.env == "dev"
    app = FastAPI(
        title="Second Brain API",
        version=API_VERSION,
        lifespan=lifespan,
        docs_url="/api/docs" if docs_enabled else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if docs_enabled else None,
    )
    app.state.settings = settings
    app.state.clock = clock
    app.state.throttle = LoginThrottle(clock=throttle_clock)
    app.state.login_lock = asyncio.Lock()

    app.add_exception_handler(PoolTimeout, _database_unavailable)
    app.add_exception_handler(psycopg.OperationalError, _database_unavailable)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _invalid_request)
    app.middleware("http")(_log_requests)

    app.include_router(health.router, prefix="/api")
    app.include_router(auth.router, prefix="/api/auth")
    return app


def openapi_schema() -> dict[str, Any]:
    """OpenAPI document without needing a real .env or database."""
    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        DATABASE_URL="postgres://unused@127.0.0.1:1/unused",  # pyright: ignore[reportCallIssue]
        owner_password_hash=PLACEHOLDER_HASH,
        env="dev",
    )
    return create_app(settings).openapi()

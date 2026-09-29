"""FastAPI application factory."""

import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import psycopg
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from psycopg_pool import PoolTimeout

from ai_second_brain.auth.throttle import LoginThrottle
from ai_second_brain.config import Settings, get_settings
from ai_second_brain.db import create_pool
from ai_second_brain.interfaces.api.routes import health

logger = logging.getLogger("ai_second_brain.api")

PLACEHOLDER_HASH = "$argon2id$v=19$m=65536,t=3,p=4$placeholder$placeholder"


def utc_now() -> datetime:
    return datetime.now(UTC)


async def _database_unavailable(request: Request, exc: Exception) -> JSONResponse:
    logger.warning("database unavailable: %s", type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "database_unavailable"})


async def _invalid_request(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": "invalid_request"})


async def _log_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "%s %s %s %.1fms", request.method, request.url.path, response.status_code, elapsed_ms
    )
    return response


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
        try:
            yield
        finally:
            await pool.close()

    docs_enabled = settings.env == "dev"
    app = FastAPI(
        title="Second Brain API",
        version="0.2.0",
        lifespan=lifespan,
        docs_url="/api/docs" if docs_enabled else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if docs_enabled else None,
    )
    app.state.settings = settings
    app.state.clock = clock
    app.state.throttle = LoginThrottle(clock=throttle_clock)

    app.add_exception_handler(PoolTimeout, _database_unavailable)
    app.add_exception_handler(psycopg.OperationalError, _database_unavailable)
    app.add_exception_handler(RequestValidationError, _invalid_request)
    app.middleware("http")(_log_requests)

    app.include_router(health.router, prefix="/api")
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

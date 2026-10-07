"""FastAPI application factory."""

import asyncio
import contextlib
import http
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import psycopg
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from procrastinate import App
from psycopg_pool import PoolTimeout
from starlette.exceptions import HTTPException as StarletteHTTPException

from ai_second_brain.auth.sessions import SessionStore
from ai_second_brain.auth.throttle import LoginThrottle
from ai_second_brain.chat.providers.base import ChatTimeouts
from ai_second_brain.chat.providers.ollama import OllamaPool, create_http_client
from ai_second_brain.chat.repository import PgChatRepository
from ai_second_brain.chat.retrieval import NullRetriever, Retriever
from ai_second_brain.chat.service import ChatService
from ai_second_brain.chat.wiring import make_cloud_factory
from ai_second_brain.config import Settings, get_settings
from ai_second_brain.db import create_pool
from ai_second_brain.interfaces.api.routes import (
    auth,
    capture,
    chat,
    graph,
    health,
    nightly,
    search,
    sources,
)
from ai_second_brain.knowledge.embedder import Embedder
from ai_second_brain.knowledge.jobs import create_job_app
from ai_second_brain.knowledge.queue import JobQueue, ProcrastinateQueue
from ai_second_brain.search.embedding import QueryEmbedder
from ai_second_brain.search.retriever import HybridRetriever

logger = logging.getLogger("ai_second_brain.api")

PLACEHOLDER_HASH = "$argon2id$v=19$m=65536,t=3,p=4$placeholder$placeholder"

# API contract version: bumped only for breaking API changes, independent of app releases,
# so a release never makes the generated web client stale.
API_VERSION = "1.0"


@dataclass
class IngestAccess:
    """What the Sources routes need from ingestion. The job app opens lazily (and again after a
    failure), so the API starts, and recovers, while the database is down."""

    job_app: App
    space_id: int
    embedder: Embedder | None
    queue: JobQueue | None = None
    _cache: tuple[float, bool] | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def get_queue(self) -> JobQueue | None:
        """The queue, opening the job app if needed; None if the database is unreachable."""
        if self.queue is not None:
            return self.queue
        async with self._lock:
            if self.queue is not None:
                return self.queue
            try:
                await self.job_app.open_async()
            except Exception as error:
                logger.warning("job_app_unavailable type=%s", type(error).__name__)
                with contextlib.suppress(Exception):  # a half-open pool would block a retry
                    await self.job_app.close_async()
                return None
            self.queue = ProcrastinateQueue(self.job_app)
            return self.queue

    async def close(self) -> None:
        if self.queue is not None:
            with contextlib.suppress(Exception):
                await self.job_app.close_async()

    async def host_reachable(self) -> bool | None:
        if self.embedder is None:
            return None
        now = time.monotonic()
        if self._cache and now - self._cache[0] < 10:
            return self._cache[1]
        result = await self.embedder.reachable()
        self._cache = (now, result)
        return result


@dataclass(frozen=True)
class GraphAccess:
    """What the graph routes need: the extraction model, if any, and whether runs can start."""

    model: str | None

    @property
    def available(self) -> bool:
        return self.model is not None


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
    retriever: Retriever | None = None,
    chat_timeouts: ChatTimeouts | None = None,
    sse_ping_interval: float = 15.0,
) -> FastAPI:
    settings = settings or get_settings()
    timeouts = chat_timeouts or ChatTimeouts()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        pool = create_pool(settings.database_url)
        await pool.open(wait=False)
        http_client = create_http_client()
        app.state.pool = pool
        app.state.sessions = SessionStore(pool, timedelta(days=settings.session_ttl_days), clock)
        app.state.ollama = OllamaPool(
            settings.ollama_endpoints,
            http_client,
            timeouts=timeouts,
            max_tokens=settings.chat_max_tokens,
            num_ctx=settings.chat_num_ctx,
            status_ttl=settings.chat_status_ttl_seconds,
        )
        embedder = (
            Embedder(settings.embed_url, settings.embed_model, 1024, http_client, timeouts)
            if settings.embed_url
            else None
        )
        app.state.query_embedder = QueryEmbedder(embedder)
        chat_retriever = retriever or (
            HybridRetriever(pool, app.state.query_embedder, settings)
            if settings.vault_path is not None
            else NullRetriever()
        )
        app.state.chat_repo = PgChatRepository(pool)
        app.state.chat = ChatService(
            app.state.chat_repo,
            chat_retriever,
            app.state.ollama,
            make_cloud_factory(settings, timeouts),
        )
        job_app = create_job_app(settings.database_url, open_timeout=2.0)
        # space 1 is seeded by the migration
        app.state.ingest = IngestAccess(job_app, 1, embedder)
        await app.state.ingest.get_queue()  # None when the database is down; retried per request
        app.state.graph = GraphAccess(settings.extract_model_name)
        try:
            await app.state.sessions.purge_expired()
        except (PoolTimeout, psycopg.Error, OSError):
            logger.warning("session purge skipped: database unavailable")
        try:
            yield
        finally:
            await app.state.ingest.close()
            await http_client.aclose()
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
    app.state.sse_ping_interval = sse_ping_interval

    app.add_exception_handler(PoolTimeout, _database_unavailable)
    app.add_exception_handler(psycopg.OperationalError, _database_unavailable)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _invalid_request)
    app.middleware("http")(_log_requests)

    app.include_router(health.router, prefix="/api")
    app.include_router(auth.router, prefix="/api/auth")
    app.include_router(chat.router, prefix="/api")
    app.include_router(sources.router, prefix="/api")
    app.include_router(search.router, prefix="/api")
    app.include_router(capture.router, prefix="/api")
    app.include_router(graph.router, prefix="/api")
    app.include_router(nightly.router, prefix="/api")
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

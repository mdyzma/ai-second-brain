"""`ai-second-brain worker`: procrastinate worker + watcher + reconcile timer, one process."""

import asyncio
import contextlib
import logging
import signal
from collections.abc import Awaitable, Callable

import httpx2
import psycopg
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from ai_second_brain.chat.providers.base import ChatTimeouts
from ai_second_brain.chat.providers.ollama import create_http_client
from ai_second_brain.config import Settings, model_matches_space
from ai_second_brain.db import create_pool
from ai_second_brain.graph.context import GraphContext
from ai_second_brain.graph.llm import ExtractClient
from ai_second_brain.knowledge import store
from ai_second_brain.knowledge.context import IngestContext
from ai_second_brain.knowledge.embedder import Embedder
from ai_second_brain.knowledge.jobs import (
    EMBED_QUEUE,
    EXTRACT_QUEUE,
    INGEST_QUEUE,
    create_job_app,
)
from ai_second_brain.knowledge.queue import ProcrastinateQueue
from ai_second_brain.search.embedding import QueryEmbedder
from ai_second_brain.vault.batch import apply_batch
from ai_second_brain.vault.paths import Vault
from ai_second_brain.vault.reconcile import reconcile
from ai_second_brain.vault.watcher import run_watcher

logger = logging.getLogger("ai_second_brain.ingest")
WAKE_MIN_SECONDS = 10.0  # a wake-triggered reconcile runs at most once per this many seconds
BACKOFF_MAX_SECONDS = 60.0  # database retry backoff: 1 s doubling up to this
DB_OPEN_TIMEOUT = 30.0
DB_ERRORS = (psycopg.OperationalError, PoolTimeout, OSError)


def _install_signals(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(ValueError, OSError):
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))


ReconcileFn = Callable[..., Awaitable[object]]


async def _guarded_reconcile(ctx: IngestContext, trigger: str, run: ReconcileFn) -> None:
    try:
        await run(ctx, trigger=trigger)
    except Exception as error:
        logger.warning("reconcile_error type=%s", type(error).__name__)


async def _sleep_unless(stop: asyncio.Event, seconds: float) -> None:
    """Sleep up to `seconds`; return early when `stop` is set."""
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=max(seconds, 0))


async def _reconcile_loop(
    ctx: IngestContext,
    stop: asyncio.Event,
    wake: asyncio.Event,
    run: ReconcileFn = reconcile,
    *,
    wake_interval: float = WAKE_MIN_SECONDS,
) -> None:
    loop = asyncio.get_running_loop()
    await _guarded_reconcile(ctx, "startup", run)
    last_finished = loop.time()
    while not stop.is_set():
        stop_wait = asyncio.create_task(stop.wait())
        wake_wait = asyncio.create_task(wake.wait())
        await asyncio.wait(
            {stop_wait, wake_wait},
            timeout=ctx.settings.reconcile_minutes * 60,
            return_when=asyncio.FIRST_COMPLETED,
        )
        stop_wait.cancel()
        wake_wait.cancel()
        if stop.is_set():
            break
        if wake.is_set():
            # At most one wake-triggered pass per interval: later wakes fold into this deadline.
            await _sleep_unless(stop, last_finished + wake_interval - loop.time())
            if stop.is_set():
                break
        wake.clear()
        await _guarded_reconcile(ctx, "schedule", run)
        last_finished = loop.time()


async def _until_stopped[T](stop: asyncio.Event, work: Awaitable[T]) -> T | None:
    """Await `work`, or cancel it and return None as soon as `stop` is set."""
    task = asyncio.ensure_future(work)
    stop_wait = asyncio.create_task(stop.wait())
    try:
        await asyncio.wait({task, stop_wait}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        stop_wait.cancel()
    if not task.done():
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
        return None
    return task.result()


def _backoff(delay: float) -> float:
    return min(delay * 2, BACKOFF_MAX_SECONDS)


async def _open_database(
    settings: Settings, stop: asyncio.Event
) -> tuple[AsyncConnectionPool, tuple[int, str, int]] | None:
    """Open the pool and read the default space, retrying with backoff until `stop`."""
    delay = 1.0
    while not stop.is_set():
        pool = create_pool(settings.database_url)

        async def connect(pool: AsyncConnectionPool = pool) -> tuple[int, str, int]:
            await pool.open(wait=True, timeout=DB_OPEN_TIMEOUT)
            async with pool.connection() as conn:
                return await store.default_space(conn)

        try:
            space = await _until_stopped(stop, connect())
        except DB_ERRORS as error:
            logger.warning("database_unavailable type=%s", type(error).__name__)
            space = None
        if space is not None:
            return pool, space
        await pool.close()
        await _sleep_unless(stop, delay)
        delay = _backoff(delay)
    return None


async def _supervise(run_once: Callable[[], Awaitable[None]], stop: asyncio.Event) -> None:
    """Run the job worker; when it exits before `stop` (e.g. Postgres restarted and its
    heartbeat failed), log it, back off (1 s doubling to 60 s) and start it again."""
    loop = asyncio.get_running_loop()
    delay = 1.0
    while not stop.is_set():
        started = loop.time()
        error: BaseException | None = None
        try:
            await _until_stopped(stop, run_once())
        except Exception as exc:
            error = exc
        if stop.is_set():
            return
        logger.warning(
            "database_unavailable type=%s", type(error).__name__ if error else "worker_exited"
        )
        if loop.time() - started >= BACKOFF_MAX_SECONDS:
            delay = 1.0  # it ran fine for a while: this is a fresh outage
        await _sleep_unless(stop, delay)
        delay = _backoff(delay)


def build_graph_context(ctx: IngestContext, http_client: httpx2.AsyncClient) -> GraphContext:
    """No client without SB_EXTRACT_MODEL: extraction then records `extraction_unavailable`."""
    settings = ctx.settings
    model = settings.extract_model_name
    client = (
        ExtractClient(
            http_client, settings.ollama_endpoints, model, ChatTimeouts(), settings.chat_num_ctx
        )
        if model
        else None
    )
    return GraphContext(ctx.pool, settings, client, QueryEmbedder(ctx.embedder), ctx.queue)


async def run_worker(settings: Settings, *, stop_event: asyncio.Event | None = None) -> int:
    """Returns 1 only when SB_EMBED_MODEL doesn't match the default space; 0 on stop."""
    stop = stop_event or asyncio.Event()
    if stop_event is None:
        _install_signals(stop)
    opened = await _open_database(settings, stop)
    if opened is None:
        return 0  # stopped while the database was unreachable
    pool, (space_id, model, dims) = opened
    try:
        if not model_matches_space(settings.embed_model, model):
            logger.error(
                "embed_model_mismatch configured=%s default_space=%s", settings.embed_model, model
            )
            print(
                f"SB_EMBED_MODEL={settings.embed_model!r} is not a tag of the default"
                f" embedding space {model!r}."
            )
            return 1
        app = create_job_app(settings.database_url)
        async with app.open_async(), create_http_client() as client:
            embedder = (
                Embedder(settings.embed_url, settings.embed_model, dims, client, ChatTimeouts())
                if settings.embed_url
                else None
            )
            vault = (
                Vault(settings.vault_path, settings.vault_excludes) if settings.vault_path else None
            )
            ctx = IngestContext(
                pool, settings, vault, embedder, ProcrastinateQueue(app), space_id, model, dims
            )

            graph_ctx = build_graph_context(ctx, client)

            def run_jobs() -> Awaitable[None]:
                return app.run_worker_async(
                    queues=[INGEST_QUEUE, EMBED_QUEUE, EXTRACT_QUEUE],
                    concurrency=2,
                    install_signal_handlers=False,
                    shutdown_graceful_timeout=30,
                    additional_context={"ingest": ctx, "graph": graph_ctx},
                )

            # The watcher and the reconcile timer guard their own errors and keep running
            # while the job worker is restarted.
            tasks = [asyncio.create_task(_supervise(run_jobs, stop))]
            if vault is None:
                await _guarded_reconcile(ctx, "startup", reconcile)  # records 'disabled'
            else:
                wake = asyncio.Event()
                tasks.append(asyncio.create_task(_reconcile_loop(ctx, stop, wake)))
                tasks.append(
                    asyncio.create_task(
                        run_watcher(vault, lambda b: apply_batch(ctx, b), stop, on_rescan=wake.set)
                    )
                )
            await stop.wait()
            for task in tasks[1:]:
                task.cancel()
            for task in tasks:  # the supervisor shuts the job worker down gracefully
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        return 0
    finally:
        await pool.close()

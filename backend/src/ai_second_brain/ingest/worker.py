"""`ai-second-brain worker`: procrastinate worker + watcher + reconcile timer, one process."""

import asyncio
import contextlib
import logging
import signal

from ai_second_brain.chat.providers.base import ChatTimeouts
from ai_second_brain.chat.providers.ollama import create_http_client
from ai_second_brain.config import Settings, model_matches_space
from ai_second_brain.db import create_pool
from ai_second_brain.knowledge import store
from ai_second_brain.knowledge.context import IngestContext
from ai_second_brain.knowledge.embedder import Embedder
from ai_second_brain.knowledge.jobs import EMBED_QUEUE, INGEST_QUEUE, create_job_app
from ai_second_brain.knowledge.queue import ProcrastinateQueue
from ai_second_brain.vault.batch import apply_batch
from ai_second_brain.vault.paths import Vault
from ai_second_brain.vault.reconcile import reconcile
from ai_second_brain.vault.watcher import run_watcher

logger = logging.getLogger("ai_second_brain.ingest")


def _install_signals(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(ValueError, OSError):
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))


async def _reconcile_loop(ctx: IngestContext, stop: asyncio.Event) -> None:
    try:
        await reconcile(ctx, trigger="startup")
    except Exception as error:
        logger.warning("reconcile_error type=%s", type(error).__name__)
    while not stop.is_set():
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=ctx.settings.reconcile_minutes * 60)
        if not stop.is_set():
            try:
                await reconcile(ctx, trigger="schedule")
            except Exception as error:
                logger.warning("reconcile_error type=%s", type(error).__name__)


async def run_worker(settings: Settings, *, stop_event: asyncio.Event | None = None) -> int:
    stop = stop_event or asyncio.Event()
    if stop_event is None:
        _install_signals(stop)
    pool = create_pool(settings.database_url)
    await pool.open(wait=True, timeout=30)
    try:
        async with pool.connection() as conn:
            space_id, model, dims = await store.default_space(conn)
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
        code = 0
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
            worker = asyncio.create_task(
                app.run_worker_async(
                    queues=[INGEST_QUEUE, EMBED_QUEUE],
                    concurrency=2,
                    install_signal_handlers=False,
                    shutdown_graceful_timeout=30,
                    additional_context={"ingest": ctx},
                )
            )
            helpers: list[asyncio.Task[None]] = []
            if vault is None:
                await reconcile(ctx, trigger="startup")  # records outcome 'disabled'
            else:
                helpers.append(asyncio.create_task(_reconcile_loop(ctx, stop)))
                helpers.append(
                    asyncio.create_task(run_watcher(vault, lambda b: apply_batch(ctx, b), stop))
                )
            stop_wait = asyncio.create_task(stop.wait())
            await asyncio.wait({stop_wait, worker}, return_when=asyncio.FIRST_COMPLETED)
            if not stop.is_set():
                error = None if worker.cancelled() else worker.exception()
                logger.error("worker_exited type=%s", type(error).__name__ if error else "none")
                code = 1
            stop_wait.cancel()
            for task in helpers:
                task.cancel()
            worker.cancel()
            for task in (stop_wait, *helpers, worker):
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        return code
    finally:
        await pool.close()

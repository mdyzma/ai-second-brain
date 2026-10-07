"""The nightly run lifecycle (spec §5.2, §5.3). Logs carry ids and counts only."""

import logging
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

import psycopg
from psycopg_pool import AsyncConnectionPool

from ai_second_brain.config import Settings
from ai_second_brain.graph.prompt import EXTRACTOR_VERSION
from ai_second_brain.graph.queries import extract_queue_depth, queue_extraction_capped
from ai_second_brain.knowledge.queue import JobQueue
from ai_second_brain.nightly import store
from ai_second_brain.nightly.schedule import run_date_for, should_start

logger = logging.getLogger("ai_second_brain.nightly")

RunStart = Literal["started", "already_started", "busy", "failed"]

# How long a run may stay open with zero counts while `start_run` is still queueing.
START_GRACE = timedelta(minutes=5)


@dataclass(frozen=True)
class StartResult:
    outcome: RunStart
    run_id: UUID | None


def _now(now: datetime | None) -> datetime:
    """The current UTC time, or `now`, which must be timezone-aware."""
    if now is None:
        return datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return now


async def start_run(
    pool: AsyncConnectionPool,
    queue: JobQueue,
    settings: Settings,
    trigger: store.Trigger,
    *,
    now: datetime | None = None,
) -> StartResult:
    """Insert the run row, then queue extraction in short steps (no transaction is held
    open while deferring). A failure after the insert records the run as failed, through a
    fresh connection, because the first one may be the thing that broke."""
    run_date = run_date_for(_now(now), settings.nightly_zone)
    failure: str | None = None
    queued_new = queued_failed = 0
    async with pool.connection() as conn:
        run_id = await store.insert_run(conn, run_date=run_date, trigger=trigger)
        await conn.commit()
        if run_id is None:
            # Only a scheduled insert can hit `nightly_runs_scheduled_day`: another worker won
            # today's run. Any other conflict is `nightly_runs_one_open`: a run is in progress.
            won = trigger == "schedule" and await store.has_scheduled_run(conn, run_date)
            outcome: RunStart = "already_started" if won else "busy"
            await conn.commit()
            logger.info("nightly_start outcome=%s trigger=%s", outcome, trigger)
            return StartResult(outcome, None)
        try:
            if settings.extract_model_name is None:
                await store.finish(conn, run_id, unavailable=True)
                await conn.commit()
                logger.info(
                    "nightly_run_started id=%s trigger=%s unavailable=true", run_id, trigger
                )
                return StartResult("started", run_id)
            queued_new, queued_failed = await queue_extraction_capped(
                conn, queue, EXTRACTOR_VERSION, settings.nightly_max_notes
            )
            await store.set_counts(conn, run_id, queued_new, queued_failed)
            if queued_new + queued_failed == 0:
                await store.finish(conn, run_id)
            await conn.commit()
        except Exception as error:
            failure = "db_error" if isinstance(error, psycopg.Error) else "queue_error"
            with suppress(Exception):  # a dead connection cannot roll back; the pool drops it
                await conn.rollback()
    if failure is not None:
        await _record_failure(pool, run_id, failure)
        return StartResult("failed", run_id)
    logger.info(
        "nightly_run_started id=%s trigger=%s queued_new=%d queued_failed=%d",
        run_id,
        trigger,
        queued_new,
        queued_failed,
    )
    return StartResult("started", run_id)


async def _record_failure(pool: AsyncConnectionPool, run_id: UUID, code: str) -> None:
    """Mark the run failed on a fresh connection. If even that fails, the run stays open with
    zero counts, and `close_open_run` marks it `start_interrupted` after the grace period."""
    try:
        async with pool.connection() as conn:
            await store.fail(conn, run_id, code)
            await conn.commit()
    except Exception:
        logger.warning("nightly_run_fail_unrecorded id=%s error=%s", run_id, code)
        raise
    logger.warning("nightly_run_failed id=%s error=%s", run_id, code)


async def close_open_run(
    pool: AsyncConnectionPool, settings: Settings, *, now: datetime | None = None
) -> UUID | None:
    """Close the open run once no extract job waits or runs, or once it has been open longer
    than `nightly_max_hours` (then `timed_out`; its jobs keep running). Stateless.

    A run still `running` with zero counts is being queued right now (`start_run` finishes a
    run that queued nothing in the same commit as its counts), so it is left alone for
    `START_GRACE`. Older than that, its start died: it is marked failed `start_interrupted`,
    and the next tick retries the day."""
    current = _now(now)
    async with pool.connection() as conn:
        run = await store.open_run(conn)
        if run is None:
            await conn.commit()
            return None
        age = current - run["started_at"]  # both timezone-aware (started_at is timestamptz)
        if run["queued_new"] + run["queued_failed"] == 0:
            if age < START_GRACE:
                await conn.commit()
                return None
            await store.fail(conn, run["id"], "start_interrupted")
            await conn.commit()
            logger.warning("nightly_run_failed id=%s error=start_interrupted", run["id"])
            return run["id"]
        timed_out = age > timedelta(hours=settings.nightly_max_hours)
        if not timed_out and await extract_queue_depth(conn) > 0:
            await conn.commit()
            return None
        await store.finish(conn, run["id"], timed_out=timed_out)
        await conn.commit()
    logger.info("nightly_run_closed id=%s timed_out=%s", run["id"], str(timed_out).lower())
    return run["id"]


async def tick(
    pool: AsyncConnectionPool, queue: JobQueue, settings: Settings, *, now: datetime | None = None
) -> None:
    """One 15-minute tick (spec §5.1): close the open run, then start today's if it is due."""
    current = _now(now)
    await close_open_run(pool, settings, now=current)
    today = run_date_for(current, settings.nightly_zone)
    async with pool.connection() as conn:
        done = await store.has_scheduled_run(conn, today)
        await conn.commit()
    go = should_start(
        current,
        settings.nightly_zone,
        settings.nightly_time,
        enabled=settings.nightly_enabled,
        has_scheduled_run_today=done,
    )
    logger.info("nightly_tick decision=%s", "start" if go else "wait")
    if go:
        await start_run(pool, queue, settings, "schedule", now=current)

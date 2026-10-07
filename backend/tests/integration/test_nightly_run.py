"""Nightly run store, capped queueing (Task 2) and the run lifecycle (Task 3)."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from ai_second_brain.config import OllamaEndpointConfig, Settings
from ai_second_brain.graph.prompt import EXTRACTOR_VERSION
from ai_second_brain.graph.queries import queue_extraction_capped
from ai_second_brain.nightly import store
from ai_second_brain.nightly.run import StartResult, close_open_run, start_run, tick
from ai_second_brain.vault.observe import observe

from ..conftest import run_async
from ..fakes.queue import RecordingQueue as BaseQueue
from ..ingest_harness import Harness, ingest_harness
from ..vaults import VaultBuilder

pytestmark = pytest.mark.integration


class RecordingQueue(BaseQueue):
    """JobQueue stand-in: records extract deferrals; ids in `locked` simulate lock hits."""

    def __init__(self, locked: set[UUID] | None = None) -> None:
        super().__init__()
        self.extracted: list[UUID] = []
        self.locked = locked or set()

    async def extract_revision(self, revision_id: UUID) -> bool:
        if revision_id in self.locked:
            return False
        self.extracted.append(revision_id)
        return True


DAY = date(2026, 10, 4)
Body = Callable[[Harness, list[UUID]], Awaitable[None]]


async def _setup(h: Harness, root: Path, n: int) -> list[UUID]:
    """Index n notes (oldest first); returns their current revision ids in that order."""
    await h.rows("TRUNCATE nightly_runs, extractions CASCADE")
    builder = VaultBuilder(root)
    for i in range(n):
        builder.write(f"n{i}.md", f"# N{i}\nnote number {i}")
    for i in range(n):
        await observe(h.ctx, f"n{i}.md")
        await h.drain()
    revs: list[UUID] = []
    for i in range(n):
        [row] = await h.rows(
            "SELECT current_revision_id AS r FROM sources WHERE external_ref = %s", f"n{i}.md"
        )
        revs.append(row["r"])
    return revs


def scenario(db_url: str, root: Path, n: int, body: Body) -> None:
    async def go() -> None:
        async with ingest_harness(db_url, root, None) as h:
            revs = await _setup(h, root, n)
            await body(h, revs)

    run_async(go())


async def _window_is_started_at(h: Harness, later: UUID | None, earlier: UUID) -> bool:
    [row] = await h.rows(
        "SELECT l.window_start = e.started_at AS ok FROM nightly_runs l, nightly_runs e"
        " WHERE l.id = %s AND e.id = %s",
        later,
        earlier,
    )
    return bool(row["ok"])


def test_insert_run_sets_window_from_previous_good_run(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness, _revs: list[UUID]) -> None:
        async with h.pool.connection() as conn:
            r1 = await store.insert_run(conn, run_date=DAY, trigger="manual")
            assert r1 is not None
            [first] = await h.rows(
                "SELECT window_start::text AS w FROM nightly_runs WHERE id = %s", r1
            )
            assert first["w"] == "-infinity"
            await store.finish(conn, r1)
            await conn.commit()
            r2 = await store.insert_run(conn, run_date=DAY, trigger="manual")
            assert r2 is not None
            assert await _window_is_started_at(h, r2, r1)
            await store.finish(conn, r2)
            await conn.commit()
            r3 = await store.insert_run(conn, run_date=DAY, trigger="manual")
            assert r3 is not None
            await store.fail(conn, r3, "boom")
            await conn.commit()
            r4 = await store.insert_run(conn, run_date=DAY, trigger="manual")
            assert r4 is not None
            assert await _window_is_started_at(h, r4, r2)  # the failed r3 is skipped

    scenario(db_url, tmp_path, 1, body)


def test_one_scheduled_run_per_day_and_one_open(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness, _revs: list[UUID]) -> None:
        async with h.pool.connection() as conn:
            assert not await store.has_scheduled_run(conn, DAY)
            s1 = await store.insert_run(conn, run_date=DAY, trigger="schedule")
            assert s1 is not None
            assert await store.insert_run(conn, run_date=DAY, trigger="schedule") is None
            assert await store.has_scheduled_run(conn, DAY)
            assert await store.insert_run(conn, run_date=DAY, trigger="manual") is None
            opened = await store.open_run(conn)
            assert opened is not None and opened["id"] == s1
            await store.set_counts(conn, s1, 3, 1)
            await conn.commit()
            await store.fail(conn, s1, "boom")
            await conn.commit()
            assert not await store.has_scheduled_run(conn, DAY)
            assert await store.open_run(conn) is None
            assert await store.insert_run(conn, run_date=DAY, trigger="schedule") is not None

    scenario(db_url, tmp_path, 1, body)


def test_capped_queue_new_before_failed_oldest_first(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness, revs: list[UUID]) -> None:
        # the oldest note is the failed one; the three pending follow in age order
        await h.rows(
            "INSERT INTO extractions (revision_id, extractor_version, status, model)"
            " VALUES (%s, %s, 'failed', 'fake')",
            revs[0],
            EXTRACTOR_VERSION,
        )
        async with h.pool.connection() as conn:
            queue = RecordingQueue()
            assert await queue_extraction_capped(conn, queue, EXTRACTOR_VERSION, 2) == (2, 0)
            assert queue.extracted == revs[1:3]
            queue = RecordingQueue()
            assert await queue_extraction_capped(conn, queue, EXTRACTOR_VERSION, 10) == (3, 1)
            assert queue.extracted == [*revs[1:], revs[0]]

    scenario(db_url, tmp_path, 4, body)


def test_capped_queue_lock_hits_not_counted(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness, revs: list[UUID]) -> None:
        async with h.pool.connection() as conn:
            queue = RecordingQueue(locked={revs[1]})
            assert await queue_extraction_capped(conn, queue, EXTRACTOR_VERSION, 10) == (2, 0)

    scenario(db_url, tmp_path, 3, body)


# --- run lifecycle (Task 3) ------------------------------------------------------------------

T0 = datetime(2026, 10, 4, 3, 0, tzinfo=UTC)  # after the 02:00 start, local zone UTC


def _settings(h: Harness, *, available: bool = True, **update: Any) -> Settings:
    endpoint = OllamaEndpointConfig(label="t", url="http://127.0.0.1:1", model="fake")
    values: dict[str, Any] = {
        "nightly_enabled": True,
        "nightly_at": "02:00",
        "timezone": "UTC",
        "ollama_endpoints": [endpoint] if available else [],
        "extract_model": "",
    }
    values.update(update)
    return h.ctx.settings.model_copy(update=values)


async def _runs(h: Harness) -> list[dict[str, Any]]:
    return await h.rows(
        "SELECT id, run_date, trigger, status, queued_new, queued_failed, finished_at,"
        " timed_out, unavailable, error FROM nightly_runs ORDER BY started_at"
    )


class FailingQueue(RecordingQueue):
    async def extract_revision(self, revision_id: UUID) -> bool:
        raise RuntimeError("queue down")


def test_start_run_queues_and_records_counts(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness, revs: list[UUID]) -> None:
        queue = RecordingQueue()
        result = await start_run(h.pool, queue, _settings(h), "manual", now=T0)
        assert result.outcome == "started" and result.run_id is not None
        assert queue.extracted == revs
        [row] = await _runs(h)
        assert row["id"] == result.run_id and row["run_date"] == DAY
        assert (row["queued_new"], row["queued_failed"], row["status"]) == (3, 0, "running")
        assert row["finished_at"] is None

    scenario(db_url, tmp_path, 3, body)


def test_start_run_zero_queued_completes(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness, _revs: list[UUID]) -> None:
        result = await start_run(h.pool, RecordingQueue(), _settings(h), "manual", now=T0)
        assert result.outcome == "started"
        [row] = await _runs(h)
        assert row["status"] == "complete" and row["finished_at"] is not None
        assert (row["queued_new"], row["queued_failed"]) == (0, 0)

    scenario(db_url, tmp_path, 0, body)


def test_start_run_unavailable_completes_with_flag(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness, _revs: list[UUID]) -> None:
        queue = RecordingQueue()
        result = await start_run(h.pool, queue, _settings(h, available=False), "schedule", now=T0)
        assert result.outcome == "started"
        assert queue.extracted == []
        [row] = await _runs(h)
        assert row["unavailable"] is True and row["status"] == "complete"
        assert row["finished_at"] is not None

    scenario(db_url, tmp_path, 2, body)


def test_manual_while_running_is_busy(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness, _revs: list[UUID]) -> None:
        settings = _settings(h)
        first = await start_run(h.pool, RecordingQueue(), settings, "manual", now=T0)
        assert first.outcome == "started"
        second = await start_run(h.pool, RecordingQueue(), settings, "manual", now=T0)
        assert second == StartResult("busy", None)
        assert len(await _runs(h)) == 1

    scenario(db_url, tmp_path, 1, body)


def test_concurrent_scheduled_starts_make_one_run(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness, _revs: list[UUID]) -> None:
        settings = _settings(h)
        results = await asyncio.gather(
            start_run(h.pool, RecordingQueue(), settings, "schedule", now=T0),
            start_run(h.pool, RecordingQueue(), settings, "schedule", now=T0),
        )
        outcomes = sorted(r.outcome for r in results)
        assert outcomes[1] == "started"
        assert outcomes[0] in ("already_started", "busy")
        assert len(await _runs(h)) == 1

    scenario(db_url, tmp_path, 2, body)


def test_scheduled_conflict_on_today_is_already_started(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness, _revs: list[UUID]) -> None:
        settings = _settings(h)
        first = await start_run(h.pool, RecordingQueue(), settings, "schedule", now=T0)
        assert first.outcome == "started"  # completes at once: nothing pending
        again = await start_run(h.pool, RecordingQueue(), settings, "schedule", now=T0)
        assert again == StartResult("already_started", None)

    scenario(db_url, tmp_path, 0, body)


def test_queue_error_marks_failed_and_next_tick_retries(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness, _revs: list[UUID]) -> None:
        settings = _settings(h)
        result = await start_run(h.pool, FailingQueue(), settings, "schedule", now=T0)
        assert result.outcome == "failed" and result.run_id is not None
        [row] = await _runs(h)
        assert (row["status"], row["error"]) == ("failed", "queue_error")
        assert row["finished_at"] is not None
        await tick(h.pool, RecordingQueue(), settings, now=T0 + timedelta(minutes=15))
        failed, retried = await _runs(h)
        assert failed["id"] == result.run_id
        assert retried["trigger"] == "schedule" and retried["run_date"] == DAY
        assert retried["status"] == "running" and retried["queued_new"] == 2

    scenario(db_url, tmp_path, 2, body)


def test_close_on_drain_and_timeout(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness, revs: list[UUID]) -> None:
        settings = _settings(h)
        now = datetime.now(UTC)
        first = await start_run(h.pool, RecordingQueue(), settings, "manual", now=now)
        assert first.outcome == "started"
        # the recording queue deferred nothing, so no extract job is waiting: drained
        assert await close_open_run(h.pool, settings, now=now) == first.run_id
        [row] = await _runs(h)
        assert row["status"] == "complete" and row["timed_out"] is False
        assert await close_open_run(h.pool, settings, now=now) is None  # nothing open

        second = await start_run(h.pool, RecordingQueue(), settings, "manual", now=now)
        assert second.outcome == "started"
        assert await h.ctx.queue.extract_revision(revs[0])  # a real `todo` extract job
        assert await close_open_run(h.pool, settings, now=datetime.now(UTC)) is None
        [_, row] = await _runs(h)
        assert row["status"] == "running"

        [opened] = await h.rows("SELECT started_at FROM nightly_runs WHERE id = %s", second.run_id)
        late = opened["started_at"] + timedelta(hours=settings.nightly_max_hours, minutes=1)
        assert await close_open_run(h.pool, settings, now=late) == second.run_id
        [_, row] = await _runs(h)
        assert row["status"] == "complete" and row["timed_out"] is True
        jobs = await h.rows(
            "SELECT 1 FROM procrastinate_jobs WHERE queue_name = 'extract' AND status = 'todo'"
        )
        assert len(jobs) == 1  # its jobs keep running

    scenario(db_url, tmp_path, 1, body)


def test_tick_disabled_never_starts(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness, _revs: list[UUID]) -> None:
        settings = _settings(h, nightly_enabled=False)
        await tick(h.pool, RecordingQueue(), settings, now=T0.replace(hour=9))
        assert await _runs(h) == []

    scenario(db_url, tmp_path, 1, body)


def test_nightly_tick_job_runs_on_the_nightly_queue(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness, _revs: list[UUID]) -> None:
        ctx = replace(h.ctx, settings=_settings(h, nightly_enabled=False))
        job = h.app.configure_task("ingest:nightly_tick")
        await job.defer_async(timestamp=1_791_000_000)  # how the periodic deferrer calls it
        await h.app.run_worker_async(
            queues=["nightly"],
            wait=False,
            install_signal_handlers=False,
            listen_notify=False,
            additional_context={"ingest": ctx},
        )
        [row] = await h.rows("SELECT status::text AS status FROM procrastinate_jobs")
        assert row["status"] == "succeeded"
        assert await _runs(h) == []  # disabled: the tick only waited

    scenario(db_url, tmp_path, 0, body)


def test_tick_waits_before_nightly_at(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness, _revs: list[UUID]) -> None:
        await tick(h.pool, RecordingQueue(), _settings(h), now=T0.replace(hour=1, minute=45))
        assert await _runs(h) == []

    scenario(db_url, tmp_path, 1, body)


def test_tick_starts_once_per_day(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness, _revs: list[UUID]) -> None:
        settings = _settings(h)
        queue = RecordingQueue()
        await tick(h.pool, queue, settings, now=T0)
        await tick(h.pool, queue, settings, now=T0 + timedelta(minutes=15))
        [row] = await _runs(h)
        assert row["trigger"] == "schedule" and row["run_date"] == DAY
        assert len(queue.extracted) == 1

    scenario(db_url, tmp_path, 1, body)

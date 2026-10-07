"""Nightly run store, capped queueing (Task 2) and the run lifecycle (Task 3)."""

from collections.abc import Awaitable, Callable
from datetime import date
from pathlib import Path
from uuid import UUID

import pytest

from ai_second_brain.graph.prompt import EXTRACTOR_VERSION
from ai_second_brain.graph.queries import queue_extraction_capped
from ai_second_brain.nightly import store
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

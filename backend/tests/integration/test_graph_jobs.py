from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import pytest

from ai_second_brain.graph.prompt import EXTRACTOR_VERSION
from ai_second_brain.graph.queries import (
    failed_revisions,
    graph_status,
    pending_revisions,
    queue_extraction,
)
from ai_second_brain.knowledge import jobs
from ai_second_brain.knowledge.queue import JobQueue, ProcrastinateQueue
from ai_second_brain.vault.observe import observe

from ..conftest import run_async
from ..fakes.ollama import FakeOllama
from ..fakes.queue import RecordingQueue
from ..ingest_harness import Harness, ingest_harness
from ..vaults import VaultBuilder

pytestmark = pytest.mark.integration

GOOD: dict[str, Any] = {
    "summary": "Rebuilding the NAS.",
    "entities": [{"name": "ZFS", "type": "tool", "aliases": [], "confidence": 0.9}],
    "relations": [{"subject": "NOTE", "relation": "mentions", "object": "ZFS", "confidence": 0.9}],
}
NOTES = {"a.md": "# A\nZFS pool notes", "b.md": "# B\nsecond note", "c.md": "# C\nthird note"}


def scenario(
    db_url: str,
    root: Path,
    body: Callable[[Harness], Awaitable[None]],
    *,
    embed_url: str | None = None,
    extract_url: str | None = None,
) -> None:
    builder = VaultBuilder(root)
    for rel, text in NOTES.items():
        builder.write(rel, text)

    async def go() -> None:
        async with ingest_harness(db_url, root, embed_url, extract_url=extract_url) as h:
            await h.rows("DELETE FROM edges")  # the harness truncate leaves the graph tables
            await h.rows("DELETE FROM entities")
            for rel in NOTES:
                await observe(h.ctx, rel)
            await h.drain()
            await body(h)

    run_async(go())


async def _revision(h: Harness, ref: str) -> UUID:
    [row] = await h.rows(
        "SELECT current_revision_id AS r FROM sources WHERE external_ref = %s", ref
    )
    return row["r"]


async def _extract_jobs(h: Harness) -> list[dict[str, Any]]:
    return await h.rows(
        "SELECT status::text AS status, args FROM procrastinate_jobs"
        " WHERE task_name = 'ingest:graph_extract_revision' ORDER BY id"
    )


async def _mark(h: Harness, revision: UUID, status: str) -> None:
    await h.rows(
        "INSERT INTO extractions (revision_id, extractor_version, status, model)"
        " VALUES (%s, %s, %s, 'fake')",
        revision,
        EXTRACTOR_VERSION,
        status,
    )


async def _pending(h: Harness) -> list[UUID]:
    async with h.pool.connection() as conn:
        return await pending_revisions(conn, EXTRACTOR_VERSION)


async def _queue(h: Harness, scope: Literal["new", "failed"], queue: JobQueue | None = None) -> int:
    async with h.pool.connection() as conn:
        return await queue_extraction(
            conn, queue or ProcrastinateQueue(h.app), EXTRACTOR_VERSION, scope
        )


def test_pending_ignores_tombstoned_noncurrent_and_ok(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness) -> None:
        a, b, c = [await _revision(h, f"{n}.md") for n in "abc"]
        assert set(await _pending(h)) == {a, b, c}
        await _mark(h, a, "ok")
        await h.rows("UPDATE sources SET deleted_at = now() WHERE external_ref = 'b.md'")
        VaultBuilder(tmp_path).write("c.md", "# C\nrewritten entirely")
        await observe(h.ctx, "c.md")
        await h.drain()
        new_c = await _revision(h, "c.md")
        assert new_c != c
        assert await _pending(h) == [new_c]  # not the old c, tombstoned b or ok a

    scenario(db_url, tmp_path, body)


def test_queue_new_is_idempotent_through_the_lock(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness) -> None:
        assert await _queue(h, "new") == 3
        assert await _queue(h, "new") == 0  # queueing locks hold
        queued = await _extract_jobs(h)
        assert len(queued) == 3 and {j["status"] for j in queued} == {"todo"}
        assert all(set(j["args"]) == {"revision_id"} for j in queued)

    scenario(db_url, tmp_path, body)


def test_retry_failed_requeues(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness) -> None:
        a, b, _ = [await _revision(h, f"{n}.md") for n in "abc"]
        await _mark(h, a, "failed")
        await _mark(h, b, "ok")
        recording = RecordingQueue()
        assert await _queue(h, "failed", recording) == 1
        assert recording.calls == [("extract", a)]
        async with h.pool.connection() as conn:
            assert await failed_revisions(conn, EXTRACTOR_VERSION) == [a]
        recording = RecordingQueue()
        assert await _queue(h, "new", recording) == 1  # c only: a is failed, b is ok
        assert recording.calls[0][0] == "extract" and recording.calls[0][1] != a

    scenario(db_url, tmp_path, body)


def test_graph_status_counts(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness) -> None:
        a, b, _ = [await _revision(h, f"{n}.md") for n in "abc"]
        await _mark(h, a, "ok")
        await _mark(h, b, "failed")
        await h.rows(
            "INSERT INTO entities (type, name, norm_name, status) VALUES"
            " ('tool','ZFS','zfs','accepted'), ('tool','Ceph','ceph','proposed'),"
            " ('person','Ann','ann','proposed'), ('person','Bob','bob','proposed')"
        )
        async with h.pool.connection() as conn:
            status = await graph_status(conn, EXTRACTOR_VERSION)
        assert status["revisions"] == {"total": 3, "extracted": 1, "failed": 1, "pending": 1}
        assert status["entities"]["tool"] == {"proposed": 1, "accepted": 1, "rejected": 0}
        assert status["entities"]["person"] == {"proposed": 2, "accepted": 0, "rejected": 0}
        assert status["entities"]["topic"] == {"proposed": 0, "accepted": 0, "rejected": 0}
        assert status["extractor_version"] == EXTRACTOR_VERSION

    scenario(db_url, tmp_path, body)


def test_drain_extracts_end_to_end_and_embeds_entity(
    db_url: str, tmp_path: Path, make_fake_ollama: Callable[[], FakeOllama]
) -> None:
    fake = make_fake_ollama()
    fake.behaviour.chat_json_by_title = {"A": [GOOD], "B": [GOOD], "C": [GOOD]}

    async def body(h: Harness) -> None:
        assert await _queue(h, "new") == 3
        await h.drain()  # extract jobs, then the embed_entity job they queue
        await h.drain()
        rows = await h.rows("SELECT status FROM extractions")
        assert [r["status"] for r in rows] == ["ok"] * 3
        [entity] = await h.rows("SELECT id FROM entities WHERE norm_name = 'zfs'")
        [emb] = await h.rows("SELECT entity_id, space_id FROM entity_embeddings")
        assert emb["entity_id"] == entity["id"] and emb["space_id"] == 1
        assert await _pending(h) == []

    scenario(db_url, tmp_path, body, embed_url=fake.url, extract_url=fake.url)


def test_embed_entity_job_is_idempotent_and_skips_missing(
    db_url: str, tmp_path: Path, make_fake_ollama: Callable[[], FakeOllama]
) -> None:
    fake = make_fake_ollama()

    async def body(h: Harness) -> None:
        [row] = await h.rows(
            "INSERT INTO entities (type, name, norm_name) VALUES ('tool','ZFS','zfs') RETURNING id"
        )
        await h.ctx.queue.embed_entity(row["id"])
        await h.ctx.queue.embed_entity(UUID(int=7))  # an entity that does not exist
        await h.drain()
        assert len(await h.rows("SELECT 1 FROM entity_embeddings")) == 1
        calls = len(fake.embed_requests())
        await h.ctx.queue.embed_entity(row["id"])
        await h.drain()
        assert len(fake.embed_requests()) == calls  # already embedded: no model call
        states = await h.rows(
            "SELECT status::text AS status FROM procrastinate_jobs"
            " WHERE task_name = 'ingest:graph_embed_entity'"
        )
        assert {s["status"] for s in states} == {"succeeded"}

    scenario(db_url, tmp_path, body, embed_url=fake.url)


def test_embed_entity_unreachable_is_rescheduled(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness) -> None:
        [row] = await h.rows(
            "INSERT INTO entities (type, name, norm_name) VALUES ('tool','ZFS','zfs') RETURNING id"
        )
        await h.ctx.queue.embed_entity(row["id"])
        await h.drain()
        [job] = await h.rows(
            "SELECT status::text AS status, attempts FROM procrastinate_jobs"
            " WHERE task_name = 'ingest:graph_embed_entity'"
        )
        assert job["status"] == "todo" and job["attempts"] == 1  # rescheduled, not failed

    scenario(db_url, tmp_path, body, embed_url="http://127.0.0.1:1")


def test_unreachable_endpoint_ends_failed_after_retries(
    db_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jobs, "EXTRACT_RETRY_SECONDS", ())

    async def body(h: Harness) -> None:
        assert await _queue(h, "new") == 3
        await h.drain()  # must not raise; the worker survives
        rows = await h.rows("SELECT status, error FROM extractions")
        assert [(r["status"], r["error"]) for r in rows] == [("failed", "extract_unreachable")] * 3
        assert {j["status"] for j in await _extract_jobs(h)} == {"succeeded"}
        async with h.pool.connection() as conn:
            assert len(await failed_revisions(conn, EXTRACTOR_VERSION)) == 3

    scenario(db_url, tmp_path, body, extract_url="http://127.0.0.1:1")


def test_unreachable_endpoint_is_retried_before_failing(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness) -> None:
        assert await _queue(h, "new") == 3
        await h.drain()
        assert await h.rows("SELECT 1 FROM extractions") == []
        assert {j["status"] for j in await _extract_jobs(h)} == {"todo"}  # rescheduled

    scenario(db_url, tmp_path, body, extract_url="http://127.0.0.1:1")


def test_final_attempt_deadlock_records_db_conflict(
    db_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from psycopg.errors import DeadlockDetected

    from ai_second_brain.graph import extract

    async def deadlock(ctx: Any, revision_id: UUID) -> str:
        raise DeadlockDetected

    monkeypatch.setattr(extract, "extract_revision", deadlock)
    monkeypatch.setattr(jobs, "EXTRACT_RETRY_SECONDS", ())

    async def body(h: Harness) -> None:
        assert await _queue(h, "new") == 3
        await h.drain()
        rows = await h.rows("SELECT status, error FROM extractions")
        assert [(r["status"], r["error"]) for r in rows] == [("failed", "extract_db_conflict")] * 3

    scenario(db_url, tmp_path, body, extract_url="http://127.0.0.1:1")


def test_mark_failed_never_overwrites_ok(db_url: str, tmp_path: Path) -> None:
    from ai_second_brain.graph.extract import mark_failed

    async def body(h: Harness) -> None:
        assert h.graph is not None
        a = await _revision(h, "a.md")
        await _mark(h, a, "ok")
        assert await mark_failed(h.graph, a, "extract_unreachable") == "skipped"
        [row] = await h.rows("SELECT status, error FROM extractions")
        assert (row["status"], row["error"]) == ("ok", None)

    scenario(db_url, tmp_path, body, extract_url="http://127.0.0.1:1")

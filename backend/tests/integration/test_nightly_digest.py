"""Digest queries (Task 4, spec §6): built from rows inserted with explicit timestamps."""

from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from ai_second_brain.graph import decide
from ai_second_brain.graph.queries import review_links
from ai_second_brain.nightly.digest import digest, latest_run_id, list_runs, run_id_for_date
from ai_second_brain.vault.observe import observe

from ..conftest import run_async
from ..ingest_harness import Harness, ingest_harness
from ..vaults import VaultBuilder

pytestmark = pytest.mark.integration

T = datetime(2026, 10, 3, 0, 0, tzinfo=UTC)
DAY = date(2026, 10, 3)
M = timedelta(minutes=1)
H = timedelta(hours=1)


class Notes:
    """The three indexed notes n0..n2: source ids and current revision ids."""

    def __init__(self, sources: list[UUID], revisions: list[UUID]) -> None:
        self.sources = sources
        self.revisions = revisions


Body = Callable[[Harness, Notes], Awaitable[None]]


async def _setup(h: Harness, root: Path) -> Notes:
    builder = VaultBuilder(root)
    for i in range(3):
        builder.write(f"n{i}.md", f"# N{i}\nnote number {i}")
    for i in range(3):
        await observe(h.ctx, f"n{i}.md")
        await h.drain()
    await h.rows("TRUNCATE nightly_runs, entities, edges, extractions CASCADE")
    sources: list[UUID] = []
    revisions: list[UUID] = []
    for i in range(3):
        [row] = await h.rows(
            "SELECT id, current_revision_id AS r FROM sources WHERE external_ref = %s",
            f"n{i}.md",
        )
        sources.append(row["id"])
        revisions.append(row["r"])
    return Notes(sources, revisions)


def scenario(db_url: str, root: Path, body: Body) -> None:
    async def go() -> None:
        async with ingest_harness(db_url, root, None) as h:
            notes = await _setup(h, root)
            await body(h, notes)

    run_async(go())


async def _run(
    h: Harness,
    *,
    started: datetime,
    finished: datetime | None,
    window: datetime | str,
    run_date: date = DAY,
    status: str = "complete",
    queued_new: int = 0,
) -> UUID:
    [row] = await h.rows(
        "INSERT INTO nightly_runs (run_date, trigger, status, window_start, started_at,"
        " finished_at, queued_new) VALUES (%s, 'manual', %s, %s::timestamptz, %s, %s, %s)"
        " RETURNING id",
        run_date,
        status,
        window if isinstance(window, str) else window.isoformat(),
        started,
        finished,
        queued_new,
    )
    return row["id"]


async def _entity(
    h: Harness,
    name: str,
    created: datetime | None,
    *,
    type_: str = "topic",
    status: str = "proposed",
) -> UUID:
    [row] = await h.rows(
        "INSERT INTO entities (type, name, norm_name, status, created_at)"
        " VALUES (%s::entity_type, %s, %s, %s::graph_status, coalesce(%s, now())) RETURNING id",
        type_,
        name,
        name.lower(),
        status,
        created,
    )
    return row["id"]


async def _edge(
    h: Harness,
    src: UUID,
    relation: str,
    dst: UUID,
    confidence: float,
    created: datetime,
    *,
    src_type: str = "entity",
    revision: UUID | None = None,
    owner: bool = False,
) -> UUID:
    """A proposed automatic edge, or with `owner` an accepted one the owner made."""
    [row] = await h.rows(
        "INSERT INTO edges (src_type, src_id, relation, dst_entity_id, confidence, origin,"
        " status, decided_by, revision_id, created_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s::graph_status, %s, %s, %s) RETURNING id",
        src_type,
        src,
        relation,
        dst,
        confidence,
        "user" if owner else "llm:fake",
        "accepted" if owner else "proposed",
        "user" if owner else "auto",
        revision,
        created,
    )
    return row["id"]


async def _extraction(
    h: Harness, revision: UUID, status: str, at: datetime | None, *, version: str = "v1"
) -> None:
    await h.rows(
        "INSERT INTO extractions (revision_id, extractor_version, status, error, model,"
        " attempted_at) VALUES (%s, %s, %s, %s, 'fake', coalesce(%s, now()))",
        revision,
        version,
        status,
        "timeout" if status == "failed" else None,
        at,
    )


async def _digest(h: Harness, run_id: UUID) -> dict[str, Any]:
    async with h.pool.connection() as conn:
        d = await digest(conn, run_id)
    assert d is not None
    return d


def test_review_lists_only_this_runs_proposed_items(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness, notes: Notes) -> None:
        run = await _run(h, started=T, finished=T + H, window=T - timedelta(days=1))
        hi = await _entity(h, "Alpha", T + 10 * M)
        lo = await _entity(h, "Bravo", T + 20 * M, type_="person")
        bare = await _entity(h, "Charlie", T + 30 * M)
        await _entity(h, "Before", T - H)
        await _entity(h, "After", T + 2 * H)
        await _entity(h, "Taken", T + 10 * M, status="accepted")
        await _edge(h, notes.sources[1], "about", hi, 0.7, T + 12 * M, src_type="source")
        await _edge(h, notes.sources[0], "mentions", hi, 0.9, T + 10 * M, src_type="source")
        await _edge(h, notes.sources[2], "mentions", lo, 0.4, T + 20 * M, src_type="source")

        d = await _digest(h, run)
        ents = d["review"]["entities"]
        assert ents["count"] == 3
        assert ents["by_type"] == {"topic": 2, "person": 1}
        assert [e["id"] for e in ents["top"]] == [hi, lo, bare]
        top = ents["top"][0]
        assert top["name"] == "Alpha" and top["type"] == "topic"
        assert top["confidence"] == pytest.approx(0.9)
        assert top["source_path"] == "n0.md"  # the earliest mention edge's note
        [src] = await h.rows("SELECT title FROM sources WHERE id = %s", notes.sources[0])
        assert top["source_title"] == src["title"]
        assert ents["top"][2]["confidence"] is None
        assert ents["top"][2]["source_path"] is None and ents["top"][2]["source_title"] is None
        # mention edges to proposed entities are not links to review (4a's Links tab)
        assert d["review"]["links"] == {"count": 0, "top": []}
        assert d["review"]["remaining"] == 3
        assert d["run"]["id"] == run and d["run"]["status"] == "complete"
        assert d["run"]["window_start"] == T - timedelta(days=1)

    scenario(db_url, tmp_path, body)


def test_reviewed_items_drop_out(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness, notes: Notes) -> None:
        run = await _run(h, started=T, finished=T + H, window=T - timedelta(days=1))
        first = await _entity(h, "Alpha", T + 10 * M)
        await _entity(h, "Bravo", T + 20 * M)
        await _edge(h, notes.sources[0], "mentions", first, 0.95, T + 10 * M, src_type="source")
        before = await _digest(h, run)
        assert before["review"]["entities"]["count"] == 2
        async with h.pool.connection() as conn:
            await decide.accept_entity(conn, first)
            await conn.commit()
        after = await _digest(h, run)
        assert after["review"]["entities"]["count"] == 1
        assert after["review"]["remaining"] == before["review"]["remaining"] - 1
        assert [e["name"] for e in after["review"]["entities"]["top"]] == ["Bravo"]

    scenario(db_url, tmp_path, body)


async def _link_ids(h: Harness, run: UUID) -> tuple[int, set[UUID], set[UUID]]:
    """The digest's link count and ids, and the ids 4a's Links tab lists."""
    d = await _digest(h, run)
    async with h.pool.connection() as conn:
        tab = await review_links(conn, cursor=None, vault_name="v")
    links = d["review"]["links"]
    return links["count"], {x["id"] for x in links["top"]}, {x["id"] for x in tab["items"]}


def test_links_follow_review_visibility(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness, notes: Notes) -> None:
        run = await _run(h, started=T, finished=T + H, window=T - timedelta(days=1))
        a = await _entity(h, "Alpha", T - 2 * H, status="accepted")
        b = await _entity(h, "Bravo", T - 2 * H, status="accepted")
        rel = await _edge(h, a, "uses", b, 0.8, T + 5 * M, revision=notes.revisions[0])
        mention = await _edge(h, notes.sources[1], "mentions", a, 0.3, T + 6 * M, src_type="source")
        early = await _edge(h, b, "part_of", a, 0.6, T - H)  # before the output window
        await _edge(h, b, "works_with", a, 1.0, T + 7 * M, owner=True)  # owner-made: never

        count, ids, _ = await _link_ids(h, run)
        assert (count, ids) == (2, {rel, mention})
        d = await _digest(h, run)
        assert [x["id"] for x in d["review"]["links"]["top"]] == [rel, mention]
        top = d["review"]["links"]["top"][0]
        assert (top["subject"], top["relation"], top["object"]) == ("Alpha", "uses", "Bravo")
        assert top["confidence"] == pytest.approx(0.8)

        # a rejected endpoint hides the relation, in the digest and in the Links tab
        await h.rows("UPDATE entities SET status = 'rejected' WHERE id = %s", b)
        count, ids, tab = await _link_ids(h, run)
        assert (count, ids) == (1, {mention})
        assert rel not in tab and mention in tab

        # restored, then its producing note tombstoned: hidden again
        await h.rows("UPDATE entities SET status = 'accepted' WHERE id = %s", b)
        assert (await _link_ids(h, run))[0] == 2
        await h.rows("UPDATE sources SET deleted_at = now() WHERE id = %s", notes.sources[0])
        count, ids, tab = await _link_ids(h, run)
        assert (count, ids) == (1, {mention})
        assert rel not in tab and mention in tab

        # a tombstoned note hides its mention link too
        await h.rows("UPDATE sources SET deleted_at = now() WHERE id = %s", notes.sources[1])
        count, ids, tab = await _link_ids(h, run)
        assert (count, ids, tab) == (0, set(), {early})  # the tab has no window

    scenario(db_url, tmp_path, body)


def test_failed_counts_only_current_live_revisions(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness, notes: Notes) -> None:
        run = await _run(h, started=T, finished=T + H, window=T - timedelta(days=1))
        await _extraction(h, notes.revisions[0], "failed", T + 10 * M)
        await _extraction(h, notes.revisions[0], "failed", T - H, version="v0")  # before
        [old] = await h.rows(
            "INSERT INTO source_revisions (source_id, content_hash, raw_text)"
            " VALUES (%s, '\\x00', 'old') RETURNING id",
            notes.sources[1],
        )
        await _extraction(h, old["id"], "failed", T + 10 * M)  # superseded revision
        await _extraction(h, notes.revisions[2], "failed", T + 10 * M)
        await h.rows("UPDATE sources SET deleted_at = now() WHERE id = %s", notes.sources[2])
        # failed at an older extractor version, then succeeded later in the window
        await _extraction(h, notes.revisions[1], "failed", T + 5 * M, version="v0")
        await _extraction(h, notes.revisions[1], "ok", T + 10 * M)

        d = await _digest(h, run)
        assert d["failed"] == {"count": 1, "items": [{"path": "n0.md", "error": "timeout"}]}

    scenario(db_url, tmp_path, body)


def test_indexed_counts(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness, notes: Notes) -> None:
        s, r = notes.sources, notes.revisions
        # n0: created in the input window, its only revision there too (not "changed")
        await h.rows("UPDATE sources SET created_at = %s WHERE id = %s", T - 2 * H, s[0])
        await h.rows("UPDATE source_revisions SET observed_at = %s WHERE id = %s", T - 2 * H, r[0])
        # n1: created earlier, a new revision in the window replaces the older one
        await h.rows(
            "UPDATE sources SET created_at = %s WHERE id = %s", T - 2 * timedelta(days=1), s[1]
        )
        await h.rows(
            "UPDATE source_revisions SET observed_at = %s WHERE id = %s",
            T - 2 * timedelta(days=1),
            r[1],
        )
        await h.rows(
            "INSERT INTO source_revisions (source_id, content_hash, raw_text, observed_at)"
            " VALUES (%s, '\\x01', 'new', %s)",
            s[1],
            T - H,
        )
        # n2: created earlier, tombstoned in the window
        await h.rows(
            "UPDATE sources SET created_at = %s, deleted_at = %s WHERE id = %s",
            T - 3 * timedelta(days=1),
            T - 30 * M,
            s[2],
        )
        await h.rows(
            "UPDATE source_revisions SET observed_at = %s WHERE id = %s",
            T - 3 * timedelta(days=1),
            r[2],
        )
        windowed = await _run(h, started=T, finished=T + H, window=T - timedelta(days=1))
        d = await _digest(h, windowed)
        assert d["indexed"] == {"created": 1, "changed": 1, "deleted": 1, "since_beginning": False}

        await h.rows("DELETE FROM nightly_runs")
        first = await _run(h, started=T, finished=T + H, window="-infinity")
        d = await _digest(h, first)
        assert d["indexed"] == {"created": 3, "changed": 1, "deleted": 1, "since_beginning": True}
        assert d["run"]["window_start"] is None

    scenario(db_url, tmp_path, body)


def test_latest_and_by_date_and_list(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness, _notes: Notes) -> None:
        async with h.pool.connection() as conn:
            assert await latest_run_id(conn) is None
            assert await list_runs(conn, 10) == []
        older = await _run(
            h,
            started=T - timedelta(days=1),
            finished=T - timedelta(days=1) + H,
            window="-infinity",
            run_date=DAY - timedelta(days=1),
        )
        early = await _run(h, started=T, finished=T + H, window=T - timedelta(days=1))
        late = await _run(h, started=T + 3 * H, finished=T + 4 * H, window=T)
        await _entity(h, "Alpha", T + 10 * M)  # in the early run's output window
        async with h.pool.connection() as conn:
            assert await latest_run_id(conn) == late
            assert await run_id_for_date(conn, DAY) == late
            assert await run_id_for_date(conn, DAY - timedelta(days=1)) == older
            assert await run_id_for_date(conn, DAY + timedelta(days=1)) is None
            runs = await list_runs(conn, 10)
            assert [x["id"] for x in runs] == [late, early, older]
            assert [x["remaining"] for x in runs] == [0, 1, 0]
            assert set(runs[0]) == {
                "id",
                "run_date",
                "trigger",
                "status",
                "started_at",
                "remaining",
            }
            assert runs[0]["run_date"] == DAY and runs[0]["trigger"] == "manual"
            assert [x["id"] for x in await list_runs(conn, 1)] == [late]
            assert await digest(conn, uuid4()) is None

    scenario(db_url, tmp_path, body)


def test_running_run_uses_now_as_window_end(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness, notes: Notes) -> None:
        [now] = await h.rows("SELECT now() AS t")
        run = await _run(
            h,
            started=now["t"] - 5 * M,
            finished=None,
            window="-infinity",
            status="running",
            queued_new=1,
        )
        await _entity(h, "Fresh", None)  # created_at = now()
        await _extraction(h, notes.revisions[0], "ok", None)
        await _extraction(h, notes.revisions[1], "ok", None)
        await _extraction(h, notes.revisions[2], "ok", now["t"] - 10 * M)  # before the run
        d = await _digest(h, run)
        assert d["review"]["entities"]["count"] == 1
        assert d["run"]["status"] == "running" and d["run"]["finished_at"] is None
        assert d["run"]["done"] == 1  # two attempted, capped at the one queued

    scenario(db_url, tmp_path, body)


def test_done_counts_only_attempts_in_the_output_window(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness, notes: Notes) -> None:
        run = await _run(h, started=T, finished=T + H, window=T - timedelta(days=1), queued_new=3)
        await _extraction(h, notes.revisions[0], "ok", T + 10 * M)
        await _extraction(h, notes.revisions[1], "ok", T + H)  # at finished_at: after
        await _extraction(h, notes.revisions[2], "failed", T + 2 * H)  # a later run's
        assert (await _digest(h, run))["run"]["done"] == 1

    scenario(db_url, tmp_path, body)


MS = timedelta(milliseconds=1)


@pytest.mark.parametrize(
    ("at", "inside"),
    [(T - MS, False), (T, True), (T + H - MS, True), (T + H, False)],
    ids=["before-start", "at-start", "before-end", "at-end"],
)
def test_output_window_edges(db_url: str, tmp_path: Path, at: datetime, inside: bool) -> None:
    """[started_at, finished_at): entities, links and failures."""

    async def body(h: Harness, notes: Notes) -> None:
        run = await _run(h, started=T, finished=T + H, window=T - timedelta(days=1))
        await _entity(h, "Edge", at)
        a = await _entity(h, "Alpha", T - 2 * H, status="accepted")
        b = await _entity(h, "Bravo", T - 2 * H, status="accepted")
        await _edge(h, a, "uses", b, 0.8, at)
        await _extraction(h, notes.revisions[0], "failed", at)
        d = await _digest(h, run)
        n = 1 if inside else 0
        assert d["review"]["entities"]["count"] == n
        assert d["review"]["links"]["count"] == n
        assert d["failed"]["count"] == n

    scenario(db_url, tmp_path, body)


@pytest.mark.parametrize(
    ("at", "inside"),
    [
        (T - timedelta(days=1) - MS, False),
        (T - timedelta(days=1), True),
        (T - MS, True),
        (T, False),
    ],
    ids=["before-start", "at-start", "before-end", "at-end"],
)
def test_input_window_edges(db_url: str, tmp_path: Path, at: datetime, inside: bool) -> None:
    """[window_start, started_at): created, changed and deleted."""

    async def body(h: Harness, notes: Notes) -> None:
        long_ago = T - timedelta(days=10)
        await h.rows("UPDATE sources SET created_at = %s", long_ago)
        await h.rows("UPDATE source_revisions SET observed_at = %s", long_ago)
        await h.rows("UPDATE sources SET created_at = %s WHERE id = %s", at, notes.sources[0])
        await h.rows("UPDATE sources SET deleted_at = %s WHERE id = %s", at, notes.sources[2])
        await h.rows(
            "INSERT INTO source_revisions (source_id, content_hash, raw_text, observed_at)"
            " VALUES (%s, '\\x01', 'new', %s)",
            notes.sources[1],
            at,
        )
        run = await _run(h, started=T, finished=T + H, window=T - timedelta(days=1))
        n = 1 if inside else 0
        d = await _digest(h, run)
        assert d["indexed"] == {"created": n, "changed": n, "deleted": n, "since_beginning": False}

    scenario(db_url, tmp_path, body)

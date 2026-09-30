from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from ai_second_brain.knowledge import store
from ai_second_brain.knowledge.index import index_source
from ai_second_brain.vault.observe import observe

from ..conftest import run_async
from ..ingest_harness import Harness, ingest_harness
from ..vaults import VaultBuilder

pytestmark = pytest.mark.integration


def run(
    db_url: str,
    root: Path,
    body: Callable[[Harness], Awaitable[None]],
    embed_url: str | None = None,
) -> None:
    async def scenario() -> None:
        async with ingest_harness(db_url, root, embed_url) as h:
            await body(h)

    run_async(scenario())


async def fts(h: Harness, word: str) -> list[str]:
    rows = await h.rows(
        "SELECT s.external_ref FROM chunks c"
        " JOIN sources s ON s.current_revision_id = c.revision_id"
        " WHERE s.deleted_at IS NULL AND c.tsv @@ plainto_tsquery('simple', %s) ORDER BY 1",
        word,
    )
    return [r["external_ref"] for r in rows]


def test_observe_is_idempotent_and_indexes(db_url: str, tmp_path: Path) -> None:
    vault = VaultBuilder(tmp_path)
    vault.write("NAS.md", "# NAS\nDyski w macierzy RAID\n")

    async def body(h: Harness) -> None:
        first = await observe(h.ctx, "NAS.md")
        second = await observe(h.ctx, "NAS.md")
        assert first is not None and first.action == "new"
        assert second is not None and second.action == "new"  # still pending, not yet indexed
        revisions = await h.rows("SELECT state FROM source_revisions")
        assert [r["state"] for r in revisions] == ["pending"]
        jobs = await h.rows("SELECT task_name FROM procrastinate_jobs")
        assert [j["task_name"] for j in jobs] == ["ingest:index_source"]
        await h.drain()
        assert await fts(h, "macierzy") == ["NAS.md"]
        third = await observe(h.ctx, "NAS.md")
        assert third is not None and third.action == "unchanged"

    run(db_url, tmp_path, body)


def test_edit_swaps_and_old_text_disappears(db_url: str, tmp_path: Path) -> None:
    vault = VaultBuilder(tmp_path)
    vault.write("a.md", "stary tekst")

    async def body(h: Harness) -> None:
        await observe(h.ctx, "a.md")
        await h.drain()
        vault.write("a.md", "nowy tekst")
        await observe(h.ctx, "a.md")
        await h.drain()
        assert await fts(h, "nowy") == ["a.md"]
        assert await fts(h, "stary") == []
        states = await h.rows(
            "SELECT state,"
            " (SELECT count(*) FROM chunks c WHERE c.revision_id = r.id) AS n"
            " FROM source_revisions r ORDER BY observed_at"
        )
        assert [(s["state"], s["n"]) for s in states] == [("superseded", 0), ("indexed", 1)]

    run(db_url, tmp_path, body)


def test_rapid_saves_index_once(db_url: str, tmp_path: Path) -> None:
    vault = VaultBuilder(tmp_path)

    async def body(h: Harness) -> None:
        for i in range(10):
            vault.write("a.md", f"wersja {i}")
            await observe(h.ctx, "a.md")
        await h.drain()
        states = await h.rows("SELECT state FROM source_revisions ORDER BY observed_at")
        assert [s["state"] for s in states] == ["superseded"] * 9 + ["indexed"]
        assert await fts(h, "9") == ["a.md"]

    run(db_url, tmp_path, body)


def test_revert_reuses_old_revision(db_url: str, tmp_path: Path) -> None:
    vault = VaultBuilder(tmp_path)

    async def body(h: Harness) -> None:
        vault.write("a.md", "A")
        await observe(h.ctx, "a.md")
        await h.drain()
        vault.write("a.md", "B")
        await observe(h.ctx, "a.md")
        await h.drain()
        vault.write("a.md", "A")
        outcome = await observe(h.ctx, "a.md")
        assert outcome is not None and outcome.action == "requeued"
        await h.drain()
        assert len(await h.rows("SELECT 1 FROM source_revisions")) == 2
        assert await fts(h, "A") == ["a.md"]

    run(db_url, tmp_path, body)


def test_crash_mid_index_rolls_back(
    db_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = VaultBuilder(tmp_path)
    vault.write("a.md", "pierwsza")

    async def body(h: Harness) -> None:
        await observe(h.ctx, "a.md")
        await h.drain()
        vault.write("a.md", "druga")
        outcome = await observe(h.ctx, "a.md")
        assert outcome is not None

        async def boom(*args: object, **kwargs: object) -> None:
            raise RuntimeError("injected crash after chunk insert")

        monkeypatch.setattr(store, "supersede_revision", boom)
        with pytest.raises(RuntimeError):
            await index_source(h.ctx, outcome.source_id)
        monkeypatch.undo()
        assert await fts(h, "pierwsza") == ["a.md"]
        pending = await h.rows("SELECT 1 FROM source_revisions WHERE state = 'pending'")
        assert len(pending) == 1
        await index_source(h.ctx, outcome.source_id)
        assert await fts(h, "druga") == ["a.md"]

    run(db_url, tmp_path, body)


def test_oversized_and_bad_encoding_fail_without_indexing(db_url: str, tmp_path: Path) -> None:
    vault = VaultBuilder(tmp_path)
    vault.write("big.md", "x" * 5000)
    vault.write("bad.md", b"\xff\xfe\x00bad")

    async def body(h: Harness) -> None:
        assert (await observe(h.ctx, "big.md")).action == "failed"  # type: ignore[union-attr]
        assert (await observe(h.ctx, "bad.md")).action == "failed"  # type: ignore[union-attr]
        rows = await h.rows("SELECT error FROM source_revisions ORDER BY error")
        assert [r["error"] for r in rows] == ["encoding", "too_large"]
        assert await h.rows("SELECT 1 FROM procrastinate_jobs") == []

    async def scenario() -> None:
        async with ingest_harness(db_url, tmp_path, None, max_note_bytes=1000) as h:
            await body(h)

    run_async(scenario())


def test_missing_file_is_io_error(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness) -> None:
        assert await observe(h.ctx, "ghost.md") is None
        assert await h.rows("SELECT 1 FROM sources") == []

    run(db_url, tmp_path, body)

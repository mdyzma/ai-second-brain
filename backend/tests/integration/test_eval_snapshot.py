from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import psycopg
import pytest

from ai_second_brain.eval import snapshot as snapshot_module
from ai_second_brain.eval.database import check_ready
from ai_second_brain.eval.queries import EvalConfigError
from ai_second_brain.eval.snapshot import live_paths, read_only_transaction, snapshot
from ai_second_brain.vault.reconcile import reconcile

from ..conftest import run_async
from ..ingest_harness import ingest_harness
from ..vaults import VaultBuilder

pytestmark = pytest.mark.integration


def test_snapshot_copies_only_live_current(  # type: ignore[no-untyped-def]
    db_url: str, eval_db_url: str, tmp_path: Path, make_fake_ollama
) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("Projects/NAS.md", "---\ntags: [homelab]\n---\n# NAS\n## Dyski\nCztery dyski.")
    vault.write("gone.md", "# Gone\nx")

    async def scenario() -> None:
        async with ingest_harness(db_url, tmp_path, fake.url) as h:
            await reconcile(h.ctx, trigger="startup")
            await h.drain()
            vault.delete("gone.md")
            await reconcile(h.ctx, trigger="schedule")
        async with (
            await psycopg.AsyncConnection.connect(db_url) as dev,
            await psycopg.AsyncConnection.connect(eval_db_url) as ev,
        ):
            await check_ready(ev)
            info = await snapshot(dev, ev)
            assert (info.sources, info.chunks) == (1, 1)
            assert await live_paths(ev) == {"Projects/NAS.md"}
            row = await (
                await ev.execute(
                    "SELECT c.heading_text, r.tags, c.tsv @@ websearch_to_tsquery('simple','dyski')"
                    " FROM chunks c JOIN source_revisions r ON r.id = c.revision_id"
                )
            ).fetchone()
            assert row == ("NAS Dyski", ["homelab"], True)
            ids = await (
                await ev.execute(
                    "SELECT s.id, r.id, c.id, r.raw_text FROM sources s"
                    " JOIN source_revisions r ON r.id = s.current_revision_id"
                    " JOIN chunks c ON c.revision_id = r.id"
                )
            ).fetchone()
            dev_ids = await (
                await dev.execute(
                    "SELECT s.id, r.id, c.id FROM sources s"
                    " JOIN source_revisions r ON r.id = s.current_revision_id"
                    " JOIN chunks c ON c.revision_id = r.id WHERE s.deleted_at IS NULL"
                )
            ).fetchone()
            await dev.rollback()  # snapshot() needs both connections idle
            await ev.rollback()
            assert ids is not None and dev_ids is not None
            assert ids[:3] == dev_ids  # ids match production
            assert ids[3] == ""  # raw_text is not copied
            again = await snapshot(dev, ev)  # idempotent: truncates first
            assert (again.sources, again.chunks) == (1, 1)
            async with dev.transaction():
                cur = await dev.execute("SELECT count(*) FROM sources WHERE deleted_at IS NULL")
                assert (await cur.fetchone()) == (1,)  # dev untouched

    run_async(scenario())


def test_dev_connection_cannot_write_inside_snapshot_transaction(db_url: str) -> None:
    async def scenario() -> None:
        async with await psycopg.AsyncConnection.connect(db_url) as dev:
            with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
                async with read_only_transaction(dev):
                    cur = await dev.execute("SHOW transaction_read_only")
                    assert (await cur.fetchone()) == ("on",)
                    await dev.execute("DELETE FROM sources")

    run_async(scenario())


def test_snapshot_reads_dev_only_inside_read_only_transaction(
    db_url: str, eval_db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Any] = []
    real = snapshot_module.read_only_transaction

    @asynccontextmanager
    async def spy(conn: psycopg.AsyncConnection[Any]) -> AsyncIterator[None]:
        async with real(conn):
            cur = await conn.execute("SHOW transaction_read_only")
            seen.append(await cur.fetchone())
            yield

    monkeypatch.setattr(snapshot_module, "read_only_transaction", spy)

    async def scenario() -> None:
        async with (
            await psycopg.AsyncConnection.connect(db_url) as dev,
            await psycopg.AsyncConnection.connect(eval_db_url) as ev,
        ):
            await snapshot(dev, ev)

    run_async(scenario())
    assert seen == [("on",)]


def test_snapshot_refuses_a_dev_connection_already_in_a_transaction(
    db_url: str, eval_db_url: str
) -> None:
    async def scenario() -> None:
        async with (
            await psycopg.AsyncConnection.connect(db_url) as dev,
            await psycopg.AsyncConnection.connect(eval_db_url) as ev,
        ):
            await dev.execute("SELECT 1")  # opens an implicit read-write transaction
            with pytest.raises(EvalConfigError):
                await snapshot(dev, ev)

    run_async(scenario())


def test_snapshot_refuses_when_target_is_the_dev_database(db_url: str) -> None:
    async def scenario() -> None:
        async with (
            await psycopg.AsyncConnection.connect(db_url) as dev,
            await psycopg.AsyncConnection.connect(db_url) as same,
        ):
            # The test DB has no eval cache either, but the identity check comes first.
            with pytest.raises(EvalConfigError) as caught:
                await snapshot(dev, same)
            assert "same database" in caught.value.errors[0]

    run_async(scenario())


def test_check_ready_needs_cache_table(db_url: str) -> None:
    async def scenario() -> None:
        async with await psycopg.AsyncConnection.connect(db_url) as conn:
            with pytest.raises(EvalConfigError):
                await check_ready(conn)  # the test DB has no eval cache

    run_async(scenario())

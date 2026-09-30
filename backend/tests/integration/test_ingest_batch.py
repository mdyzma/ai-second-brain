from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from ai_second_brain.vault.batch import apply_batch
from ai_second_brain.vault.reconcile import reconcile

from ..conftest import run_async
from ..fakes.ollama import FakeOllama
from ..ingest_harness import Harness, ingest_harness
from ..vaults import VaultBuilder

pytestmark = pytest.mark.integration
MakeFake = Callable[[], FakeOllama]


def run(
    db_url: str, root: Path, fake: FakeOllama, body: Callable[[Harness], Awaitable[None]]
) -> None:
    async def scenario() -> None:
        async with ingest_harness(db_url, root, fake.url) as h:
            await body(h)

    run_async(scenario())


async def live(h: Harness) -> list[str]:
    rows = await h.rows("SELECT external_ref FROM sources WHERE deleted_at IS NULL ORDER BY 1")
    return [r["external_ref"] for r in rows]


def test_apply_batch_rename_keeps_source(
    db_url: str, tmp_path: Path, make_fake_ollama: MakeFake
) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("a.md", "treść")

    async def body(h: Harness) -> None:
        await reconcile(h.ctx, trigger="startup")
        [before] = await h.rows("SELECT id FROM sources")
        vault.rename("a.md", "b.md")
        await apply_batch(h.ctx, [("deleted", "a.md"), ("added", "b.md")])
        [after] = await h.rows("SELECT id, external_ref FROM sources")
        assert (after["id"], after["external_ref"]) == (before["id"], "b.md")

    run(db_url, tmp_path, fake, body)


def test_apply_batch_deleted_but_present_is_observed(
    db_url: str, tmp_path: Path, make_fake_ollama: MakeFake
) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("a.md", "stara")

    async def body(h: Harness) -> None:
        await reconcile(h.ctx, trigger="startup")
        await h.drain()
        vault.write("a.md", "nowa")  # Obsidian's temp-file + rename reports delete then add
        await apply_batch(h.ctx, [("deleted", "a.md"), ("added", "a.md")])
        await h.drain()
        assert await live(h) == ["a.md"]
        rows = await h.rows("SELECT state FROM source_revisions ORDER BY observed_at")
        assert [r["state"] for r in rows] == ["superseded", "indexed"]

    run(db_url, tmp_path, fake, body)


def test_apply_batch_delete_tombstones(
    db_url: str, tmp_path: Path, make_fake_ollama: MakeFake
) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("a.md", "x")
    vault.write("b.md", "y")

    async def body(h: Harness) -> None:
        await reconcile(h.ctx, trigger="startup")
        vault.delete("a.md")
        await apply_batch(h.ctx, [("deleted", "a.md")])
        assert await live(h) == ["b.md"]

    run(db_url, tmp_path, fake, body)


def test_run_worker_returns_zero_when_stopped_without_vault(db_url: str) -> None:
    import asyncio

    from ai_second_brain.config import Settings
    from ai_second_brain.ingest.worker import run_worker

    from ..conftest import TEST_HASH

    values: dict[str, Any] = {
        "DATABASE_URL": db_url,
        "owner_password_hash": TEST_HASH,
        "vault_path": None,
    }
    settings = Settings(_env_file=None, **values)  # pyright: ignore[reportCallIssue]

    async def scenario() -> int:
        stop = asyncio.Event()
        stop.set()
        return await asyncio.wait_for(run_worker(settings, stop_event=stop), 60)

    assert run_async(scenario()) == 0


def test_apply_batch_case_only_rename_is_a_move(
    db_url: str, tmp_path: Path, make_fake_ollama: MakeFake, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_second_brain.vault.paths import Vault

    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("Note.md", "treść")

    async def body(h: Harness) -> None:
        await reconcile(h.ctx, trigger="startup")
        [before] = await h.rows("SELECT id FROM sources")
        vault.rename("Note.md", "note.md")
        # a case-insensitive disk (NTFS, APFS) still opens "Note.md"; only the listing tells
        monkeypatch.setattr(Vault, "exists_exact", lambda self, rel: rel == "note.md")
        await apply_batch(h.ctx, [("deleted", "Note.md"), ("added", "note.md")])
        rows = await h.rows("SELECT id, external_ref, deleted_at FROM sources")
        assert [(r["id"], r["external_ref"], r["deleted_at"]) for r in rows] == [
            (before["id"], "note.md", None)
        ]

    run(db_url, tmp_path, fake, body)


def test_apply_batch_tombstones_a_failed_only_source(
    db_url: str, tmp_path: Path, make_fake_ollama: MakeFake
) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("big.md", "x" * 3_000_000)

    async def body(h: Harness) -> None:
        await reconcile(h.ctx, trigger="startup")
        vault.delete("big.md")
        await apply_batch(h.ctx, [("deleted", "big.md")])
        assert await live(h) == []

    run(db_url, tmp_path, fake, body)

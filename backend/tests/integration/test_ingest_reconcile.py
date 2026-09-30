import asyncio
from collections.abc import Callable
from pathlib import Path

import pytest

from ai_second_brain.vault import reconcile as reconcile_module
from ai_second_brain.vault.observe import observe
from ai_second_brain.vault.paths import Vault, VaultWalkError
from ai_second_brain.vault.reconcile import apply_moves_and_deletes, reconcile

from ..conftest import run_async
from ..fakes.ollama import FakeOllama
from ..ingest_harness import Harness, ingest_harness
from ..vaults import VaultBuilder

pytestmark = pytest.mark.integration
MakeFake = Callable[[], FakeOllama]


def run(db_url: str, root: Path, embed_url: str | None, body: Callable[[Harness], object]) -> None:
    async def scenario() -> None:
        async with ingest_harness(db_url, root, embed_url) as h:
            await body(h)  # type: ignore[misc]

    run_async(scenario())


async def live(h: Harness) -> list[str]:
    rows = await h.rows("SELECT external_ref FROM sources WHERE deleted_at IS NULL ORDER BY 1")
    return [r["external_ref"] for r in rows]


async def last_run(h: Harness) -> dict:
    [row] = await h.rows("SELECT outcome, counts FROM ingest_runs ORDER BY id DESC LIMIT 1")
    return row


def test_initial_scan_and_offline_changes(
    db_url: str, tmp_path: Path, make_fake_ollama: MakeFake
) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("a.md", "alfa")
    vault.write("b.md", "bravo")
    vault.write(".obsidian/app.md", "ignored")

    async def body(h: Harness) -> None:
        outcome, counts = await reconcile(h.ctx, trigger="startup")
        await h.drain()
        assert (outcome, counts.new) == ("ok", 2)
        assert await live(h) == ["a.md", "b.md"]
        vault.write("a.md", "alfa zmieniona")
        vault.delete("b.md")
        vault.write("c.md", "charlie")
        outcome, counts = await reconcile(h.ctx, trigger="schedule")
        await h.drain()
        assert (counts.changed, counts.new, counts.tombstoned) == (1, 1, 1)
        assert await live(h) == ["a.md", "c.md"]
        assert (await last_run(h))["outcome"] == "ok"

    run(db_url, tmp_path, fake.url, body)


def test_tombstone_restore_and_move(
    db_url: str, tmp_path: Path, make_fake_ollama: MakeFake
) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("Notes/x.md", "unikalna treść")

    async def body(h: Harness) -> None:
        await reconcile(h.ctx, trigger="startup")
        await h.drain()
        [before] = await h.rows("SELECT id FROM sources")
        vault.rename("Notes/x.md", "Archive/x.md")
        _, counts = await reconcile(h.ctx, trigger="schedule")
        assert (counts.moved, counts.tombstoned, counts.new) == (1, 0, 0)
        [after] = await h.rows("SELECT id, external_ref FROM sources")
        assert after["id"] == before["id"] and after["external_ref"] == "Archive/x.md"
        assert len(await h.rows("SELECT 1 FROM source_revisions")) == 1
        vault.delete("Archive/x.md")
        await reconcile(h.ctx, trigger="schedule")
        assert await live(h) == []
        assert await h.rows("SELECT 1 FROM chunks") == []
        vault.write("Archive/x.md", "unikalna treść")
        _, counts = await reconcile(h.ctx, trigger="schedule")
        await h.drain()
        assert await live(h) == ["Archive/x.md"]
        assert len(await h.rows("SELECT 1 FROM chunks")) == 1

    run(db_url, tmp_path, fake.url, body)


def test_copy_is_not_a_move(db_url: str, tmp_path: Path, make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("a.md", "ta sama treść")

    async def body(h: Harness) -> None:
        await reconcile(h.ctx, trigger="startup")
        vault.write("copy.md", "ta sama treść")
        _, counts = await reconcile(h.ctx, trigger="schedule")
        assert (counts.moved, counts.new) == (0, 1)
        assert await live(h) == ["a.md", "copy.md"]

    run(db_url, tmp_path, fake.url, body)


def test_guard_trips_and_cli_override(
    db_url: str, tmp_path: Path, make_fake_ollama: MakeFake
) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    for i in range(40):
        vault.write(f"n{i}.md", f"note {i}")

    async def body(h: Harness) -> None:
        await reconcile(h.ctx, trigger="startup")
        for i in range(11):
            vault.delete(f"n{i}.md")
        outcome, counts = await reconcile(h.ctx, trigger="schedule")
        assert (outcome, counts.tombstoned, counts.missing) == ("guard_tripped", 0, 11)
        assert (await last_run(h))["counts"]["missing"] == 11
        assert len(await live(h)) == 40
        outcome, counts = await reconcile(h.ctx, trigger="cli", allow_mass_delete=True)
        assert (outcome, counts.tombstoned) == ("ok", 11)

    run(db_url, tmp_path, fake.url, body)


def test_missing_vault_tombstones_nothing(
    db_url: str, tmp_path: Path, make_fake_ollama: MakeFake
) -> None:
    fake = make_fake_ollama()
    root = tmp_path / "vault"
    VaultBuilder(root).write("a.md", "alfa")

    async def body(h: Harness) -> None:
        await reconcile(h.ctx, trigger="startup")
        (root / "a.md").unlink()
        root.rmdir()
        outcome, _ = await reconcile(h.ctx, trigger="schedule")
        assert outcome == "vault_unavailable"
        assert await live(h) == ["a.md"]

    run(db_url, root, fake.url, body)


def test_unreadable_directory_tombstones_nothing(
    db_url: str, tmp_path: Path, make_fake_ollama: MakeFake, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = make_fake_ollama()
    VaultBuilder(tmp_path).write("a.md", "alfa")

    async def body(h: Harness) -> None:
        await reconcile(h.ctx, trigger="startup")

        def broken(self: Vault) -> dict[str, tuple[int, int]]:
            raise VaultWalkError("unreadable")

        monkeypatch.setattr(Vault, "walk", broken)
        outcome, counts = await reconcile(h.ctx, trigger="schedule")
        assert (outcome, counts.tombstoned) == ("vault_unavailable", 0)
        assert (await last_run(h))["outcome"] == "vault_unavailable"
        assert await live(h) == ["a.md"]

    run(db_url, tmp_path, fake.url, body)


def test_recovery_requeues_index_and_embed(
    db_url: str, tmp_path: Path, make_fake_ollama: MakeFake
) -> None:
    fake = make_fake_ollama()
    VaultBuilder(tmp_path).write("a.md", "alfa")

    async def body(h: Harness) -> None:
        await reconcile(h.ctx, trigger="startup")
        await h.rows(
            "DELETE FROM procrastinate_jobs"
        )  # simulate a crash after commit, before defer
        _, counts = await reconcile(h.ctx, trigger="schedule")
        assert counts.requeued_index == 1
        fake.behaviour.embed_status = 500
        await h.drain()
        await h.rows("DELETE FROM procrastinate_jobs")
        fake.behaviour.embed_status = 200
        _, counts = await reconcile(h.ctx, trigger="schedule")
        assert counts.requeued_embed == 1
        await h.drain()
        assert len(await h.rows("SELECT 1 FROM chunk_embeddings")) == 1

    run(db_url, tmp_path, fake.url, body)


def test_stalled_jobs_are_reset(db_url: str, tmp_path: Path, make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    VaultBuilder(tmp_path).write("a.md", "alfa")

    async def body(h: Harness) -> None:
        await reconcile(h.ctx, trigger="startup")
        [worker] = await h.rows(
            "INSERT INTO procrastinate_workers (last_heartbeat)"
            " VALUES (now() - interval '1 hour') RETURNING id"
        )
        await h.rows(
            "UPDATE procrastinate_jobs SET status = 'doing', worker_id = %s"
            " WHERE task_name = 'ingest:index_source' RETURNING id",
            worker["id"],
        )
        _, counts = await reconcile(h.ctx, trigger="schedule")
        assert counts.stalled_reset == 1

    run(db_url, tmp_path, fake.url, body)


def test_revert_before_indexing_is_stable_and_still_moves(
    db_url: str, tmp_path: Path, make_fake_ollama: MakeFake
) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("a.md", "wersja pierwsza")

    async def body(h: Harness) -> None:
        await reconcile(h.ctx, trigger="startup")
        await h.drain()
        vault.write("a.md", "wersja druga, dluzsza")
        await reconcile(h.ctx, trigger="schedule")  # B observed, still pending
        vault.write("a.md", "wersja pierwsza")  # revert to A before indexing
        await reconcile(h.ctx, trigger="schedule")
        _, counts = await reconcile(h.ctx, trigger="schedule")
        assert counts.changed == 0
        vault.rename("a.md", "b.md")
        _, counts = await reconcile(h.ctx, trigger="schedule")
        assert (counts.moved, counts.tombstoned, counts.new) == (1, 0, 0)

    run(db_url, tmp_path, fake.url, body)


def test_stale_deleted_key_is_skipped(
    db_url: str, tmp_path: Path, make_fake_ollama: MakeFake
) -> None:
    fake = make_fake_ollama()
    VaultBuilder(tmp_path).write("a.md", "alfa")

    async def body(h: Harness) -> None:
        await reconcile(h.ctx, trigger="startup")
        result = await apply_moves_and_deletes(
            h.ctx, {"gone.md": b"x" * 32}, {}, guard=True, allow_mass_delete=False
        )
        assert (result.moved, result.tombstoned) == (0, 0)
        assert await live(h) == ["a.md"]

    run(db_url, tmp_path, fake.url, body)


def test_cancelled_reconcile_is_recorded_as_interrupted(
    db_url: str, tmp_path: Path, make_fake_ollama: MakeFake, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = make_fake_ollama()
    VaultBuilder(tmp_path).write("a.md", "alfa")

    async def body(h: Harness) -> None:
        async def cancelled(conn: object) -> list[object]:
            raise asyncio.CancelledError

        monkeypatch.setattr(reconcile_module.store, "pending_sources", cancelled)
        with pytest.raises(asyncio.CancelledError):
            await reconcile(h.ctx, trigger="schedule")
        assert (await last_run(h))["outcome"] == "interrupted"

    run(db_url, tmp_path, fake.url, body)


def test_note_observed_during_the_walk_is_not_tombstoned(
    db_url: str, tmp_path: Path, make_fake_ollama: MakeFake, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("a.md", "alfa")
    real_walk = Vault.walk

    async def body(h: Harness) -> None:
        loop = asyncio.get_running_loop()

        def stale_walk(self: Vault) -> dict[str, tuple[int, int]]:
            listing = real_walk(self)  # taken before the note exists
            vault.write("Ideas/New.md", "nowy pomysł")
            # the watcher records it while the walk is still running
            asyncio.run_coroutine_threadsafe(observe(h.ctx, "Ideas/New.md"), loop).result(10)
            return listing

        monkeypatch.setattr(Vault, "walk", stale_walk)
        outcome, counts = await reconcile(h.ctx, trigger="schedule")
        assert (outcome, counts.tombstoned) == ("ok", 0)
        assert set(await live(h)) == {"Ideas/New.md", "a.md"}

    run(db_url, tmp_path, fake.url, body)


def test_a_path_back_on_disk_is_not_tombstoned(
    db_url: str, tmp_path: Path, make_fake_ollama: MakeFake
) -> None:
    fake = make_fake_ollama()
    VaultBuilder(tmp_path).write("a.md", "alfa")

    async def body(h: Harness) -> None:
        await reconcile(h.ctx, trigger="startup")
        [row] = await h.rows("SELECT content_hash FROM source_revisions")
        result = await apply_moves_and_deletes(
            h.ctx, {"a.md": bytes(row["content_hash"])}, {}, guard=True, allow_mass_delete=False
        )
        assert result.tombstoned == 0
        assert await live(h) == ["a.md"]

    run(db_url, tmp_path, fake.url, body)


def test_failed_only_source_is_tombstoned_when_deleted(
    db_url: str, tmp_path: Path, make_fake_ollama: MakeFake
) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("big.md", "x" * 3_000_000)
    vault.write("keep.md", "zostaje")

    async def body(h: Harness) -> None:
        await reconcile(h.ctx, trigger="startup")
        vault.delete("big.md")
        outcome, counts = await reconcile(h.ctx, trigger="schedule")
        assert (outcome, counts.tombstoned) == ("ok", 1)
        assert await live(h) == ["keep.md"]

    run(db_url, tmp_path, fake.url, body)


def test_move_onto_a_path_taken_meanwhile_is_unpaired(
    db_url: str, tmp_path: Path, make_fake_ollama: MakeFake, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_second_brain.knowledge import store

    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("a.md", "ta sama treść")

    async def body(h: Harness) -> None:
        await reconcile(h.ctx, trigger="startup")
        # an old tombstoned row holds b.md, and the check-then-act gap lets the move collide
        await h.rows(
            "INSERT INTO sources (kind, external_ref, deleted_at)"
            " VALUES ('obsidian', 'b.md', now())"
        )

        async def never_taken(conn: object, rel: str) -> bool:
            return False

        monkeypatch.setattr(store, "path_taken", never_taken)
        vault.rename("a.md", "b.md")
        outcome, counts = await reconcile(h.ctx, trigger="schedule")
        assert (outcome, counts.moved, counts.tombstoned) == ("ok", 0, 1)
        assert await live(h) == ["b.md"]

    run(db_url, tmp_path, fake.url, body)

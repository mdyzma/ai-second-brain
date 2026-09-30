import dataclasses
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from ai_second_brain.knowledge.embed import EmbedRetryable, embed_revision
from ai_second_brain.vault.observe import observe

from ..conftest import run_async
from ..fakes.ollama import FakeOllama
from ..ingest_harness import Harness, ingest_harness
from ..vaults import VaultBuilder

pytestmark = pytest.mark.integration
MakeFake = Callable[[], FakeOllama]


def long_note(sections: int) -> str:
    return "\n".join(f"## Sekcja {i}\ntreść {i} " + "słowo " * 20 for i in range(sections))


async def revision_id(h: Harness) -> object:
    [row] = await h.rows("SELECT current_revision_id AS id FROM sources")
    return row["id"]


async def embedded(h: Harness) -> tuple[int, int]:
    [row] = await h.rows(
        "SELECT count(c.id) AS total, count(e.chunk_id) AS done FROM sources s"
        " JOIN chunks c ON c.revision_id = s.current_revision_id"
        " LEFT JOIN chunk_embeddings e ON e.chunk_id = c.id AND e.space_id = 1"
    )
    return row["done"], row["total"]


def run(
    db_url: str, root: Path, fake: FakeOllama, body: Callable[[Harness], object], **kw: Any
) -> None:
    async def scenario() -> None:
        async with ingest_harness(db_url, root, fake.url, **kw) as h:
            await body(h)  # type: ignore[misc]

    run_async(scenario())


def test_embeds_all_chunks_with_title_context(
    db_url: str, tmp_path: Path, make_fake_ollama: MakeFake
) -> None:
    fake = make_fake_ollama()
    VaultBuilder(tmp_path).write("NAS.md", long_note(3))

    async def body(h: Harness) -> None:
        await observe(h.ctx, "NAS.md")
        await h.drain()
        assert await embedded(h) == (3, 3)
        inputs = [text for r in fake.embed_requests() for text in r.body["input"]]
        assert inputs[0].startswith("NAS › Sekcja 0\n\n")

    run(db_url, tmp_path, fake, body)


def test_crash_between_batches_resumes(
    db_url: str, tmp_path: Path, make_fake_ollama: MakeFake
) -> None:
    fake = make_fake_ollama()
    VaultBuilder(tmp_path).write("a.md", long_note(5))

    async def body(h: Harness) -> None:
        await observe(h.ctx, "a.md")
        await h.drain()  # index ok; embed batch 1 ok, batch 2 → 500 → retry scheduled later
        assert await embedded(h) == (2, 5)
        fake.behaviour.embed_fail_on_call = None
        before = len(fake.embed_requests())
        await embed_revision(h.ctx, await revision_id(h), 1)  # type: ignore[arg-type]
        assert await embedded(h) == (5, 5)
        sent = [t for r in fake.embed_requests()[before:] for t in r.body["input"]]
        assert len(sent) == 3

    fake.behaviour.embed_fail_on_call = 2
    run(db_url, tmp_path, fake, body, embed_batch=2)


def test_unreachable_keeps_text_search_and_records_code(
    db_url: str, tmp_path: Path, make_fake_ollama: MakeFake
) -> None:
    fake = make_fake_ollama()
    VaultBuilder(tmp_path).write("a.md", "tekst do znalezienia")
    fake.behaviour.embed_status = 500

    async def body(h: Harness) -> None:
        await observe(h.ctx, "a.md")
        await h.drain()
        [row] = await h.rows(
            "SELECT r.state, r.metadata->>'embed_error' AS code FROM sources s"
            " JOIN source_revisions r ON r.id = s.current_revision_id"
        )
        assert (row["state"], row["code"]) == ("indexed", "embed_unreachable")
        assert await embedded(h) == (0, 1)
        fake.behaviour.embed_status = 200
        await embed_revision(h.ctx, await revision_id(h), 1)  # type: ignore[arg-type]
        [row] = await h.rows(
            "SELECT r.metadata->>'embed_error' AS code FROM sources s"
            " JOIN source_revisions r ON r.id = s.current_revision_id"
        )
        assert row["code"] is None
        assert await embedded(h) == (1, 1)

    run(db_url, tmp_path, fake, body)


def test_unreachable_raises_retryable(
    db_url: str, tmp_path: Path, make_fake_ollama: MakeFake
) -> None:
    fake = make_fake_ollama()
    VaultBuilder(tmp_path).write("a.md", "x")

    async def body(h: Harness) -> None:
        await observe(h.ctx, "a.md")
        await h.drain()
        fake.behaviour.embed_status = 503
        await h.rows("DELETE FROM chunk_embeddings")
        with pytest.raises(EmbedRetryable):
            await embed_revision(h.ctx, await revision_id(h), 1)  # type: ignore[arg-type]

    run(db_url, tmp_path, fake, body)


def test_model_missing_is_permanent(
    db_url: str, tmp_path: Path, make_fake_ollama: MakeFake
) -> None:
    fake = make_fake_ollama()
    fake.behaviour.embed_status = 404
    fake.behaviour.embed_error_text = 'model "bge-m3" not found, try pulling it first'
    VaultBuilder(tmp_path).write("a.md", "x")

    async def body(h: Harness) -> None:
        await observe(h.ctx, "a.md")
        await h.drain()
        [row] = await h.rows(
            "SELECT r.metadata->>'embed_error' AS code FROM sources s"
            " JOIN source_revisions r ON r.id = s.current_revision_id"
        )
        assert row["code"] == "embed_model_missing"
        jobs = await h.rows(
            "SELECT status FROM procrastinate_jobs WHERE task_name = 'ingest:embed_revision'"
        )
        assert [j["status"] for j in jobs] == ["succeeded"]  # recorded, not retried

    run(db_url, tmp_path, fake, body)


def test_empty_note_indexes_with_zero_chunks(
    db_url: str, tmp_path: Path, make_fake_ollama: MakeFake
) -> None:
    fake = make_fake_ollama()
    VaultBuilder(tmp_path).write("empty.md", "   \n\n")

    async def body(h: Harness) -> None:
        await observe(h.ctx, "empty.md")
        await h.drain()
        [row] = await h.rows(
            "SELECT r.state FROM sources s JOIN source_revisions r ON r.id = s.current_revision_id"
        )
        assert row["state"] == "indexed"
        assert await embedded(h) == (0, 0)
        assert fake.embed_requests() == []

    run(db_url, tmp_path, fake, body)


def test_embed_skips_superseded_revision(
    db_url: str, tmp_path: Path, make_fake_ollama: MakeFake
) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("a.md", "pierwsza")

    async def body(h: Harness) -> None:
        await observe(h.ctx, "a.md")
        await h.drain()
        old = await revision_id(h)
        vault.write("a.md", "druga")
        await observe(h.ctx, "a.md")
        await h.drain()
        before = len(fake.embed_requests())
        await embed_revision(h.ctx, old, 1)  # type: ignore[arg-type]
        assert len(fake.embed_requests()) == before

    run(db_url, tmp_path, fake, body)


class StaleningEmbedder:
    """Embedder stand-in that supersedes the revision while embedding `stale_on_call`."""

    def __init__(self, h: Harness, stale_on_call: int) -> None:
        self.h, self.stale_on_call, self.calls = h, stale_on_call, 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        if self.calls == self.stale_on_call:
            await self.h.rows(
                "DELETE FROM chunks WHERE revision_id IN (SELECT current_revision_id FROM sources)"
            )
        return [[0.1] * 1024 for _ in texts]


@pytest.mark.parametrize("stale_on_call", [1, 2])
def test_revision_going_stale_mid_embedding_stops_quietly(
    db_url: str, tmp_path: Path, make_fake_ollama: MakeFake, stale_on_call: int
) -> None:
    fake = make_fake_ollama()
    VaultBuilder(tmp_path).write("a.md", long_note(5))

    async def body(h: Harness) -> None:
        await observe(h.ctx, "a.md")
        fake.behaviour.embed_status = 500
        await h.drain()  # indexed, nothing embedded
        stub = StaleningEmbedder(h, stale_on_call)
        ctx = dataclasses.replace(h.ctx, embedder=stub)  # type: ignore[arg-type]
        await embed_revision(ctx, await revision_id(h), 1)  # type: ignore[arg-type]
        assert stub.calls == stale_on_call
        assert await embedded(h) == (0, 0)
        [row] = await h.rows("SELECT count(*) AS n FROM chunk_embeddings")
        assert row["n"] == 0

    run(db_url, tmp_path, fake, body, embed_batch=2)

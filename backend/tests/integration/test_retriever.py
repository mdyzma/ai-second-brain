from collections.abc import Callable
from pathlib import Path

import pytest

from ai_second_brain.search.embedding import QueryEmbedder
from ai_second_brain.search.retriever import HybridRetriever
from ai_second_brain.vault.reconcile import reconcile

from ..conftest import run_async
from ..fakes.ollama import FakeOllama
from ..ingest_harness import ingest_harness
from ..vaults import VaultBuilder

pytestmark = pytest.mark.integration


def test_retriever_cutoff_cap_and_links(
    db_url: str, tmp_path: Path, make_fake_ollama: Callable[[], FakeOllama]
) -> None:
    fake = make_fake_ollama()
    fake.behaviour.embed_topics = {"backup": "backup", "kopie zapasowe": "backup"}
    vault = VaultBuilder(tmp_path / "Brain")
    vault.write("NAS.md", "# NAS\n## Kopie zapasowe\nCo noc o 02:00.")
    vault.write("Cats.md", "# Cats\nMeow.")

    async def scenario() -> None:
        async with ingest_harness(db_url, tmp_path / "Brain", fake.url) as h:
            await reconcile(h.ctx, trigger="startup")
            await h.drain()
            retriever = HybridRetriever(h.pool, QueryEmbedder(h.ctx.embedder), h.ctx.settings)
            result = await retriever.retrieve("when does the backup run?", 8)
            assert result.mode == "hybrid"
            assert [s.path for s in result.sources] == ["NAS.md"]  # Cats is below the floor
            [source] = result.sources
            assert source.heading == "Kopie zapasowe" and source.snippet.startswith("Co noc")
            assert source.obsidian_url == "obsidian://open?vault=Brain&file=NAS.md"
            fake.behaviour.embed_status = 500
            text_only = await HybridRetriever(
                h.pool, QueryEmbedder(h.ctx.embedder), h.ctx.settings
            ).retrieve("kopie zapasowe NAS", 8)
            assert text_only.mode == "text_only"
            assert [s.path for s in text_only.sources] == ["NAS.md"]

    run_async(scenario())


class RecordingQueryEmbedder(QueryEmbedder):
    def __init__(self) -> None:
        super().__init__(None)
        self.timeouts: list[float | None] = []

    async def embed(self, text: str, *, timeout: float | None = None) -> list[float] | None:  # noqa: ASYNC109
        self.timeouts.append(timeout)
        return None


def test_retriever_gives_a_cold_model_eight_seconds(
    db_url: str, tmp_path: Path, make_fake_ollama: Callable[[], FakeOllama]
) -> None:
    fake = make_fake_ollama()
    VaultBuilder(tmp_path / "Brain").write("NAS.md", "# NAS\nKopie zapasowe co noc.")

    async def scenario() -> None:
        async with ingest_harness(db_url, tmp_path / "Brain", fake.url) as h:
            embedder = RecordingQueryEmbedder()
            result = await HybridRetriever(h.pool, embedder, h.ctx.settings).retrieve(
                "kopie zapasowe", 8
            )
            assert result.mode == "text_only"
            assert embedder.timeouts == [8.0]

    run_async(scenario())

from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

import pytest

from ai_second_brain.search.query import query
from ai_second_brain.search.terms import chat_terms
from ai_second_brain.vault.reconcile import reconcile

from ..conftest import run_async
from ..fakes.ollama import FakeOllama, fake_vector
from ..ingest_harness import Harness, ingest_harness
from ..vaults import VaultBuilder

pytestmark = pytest.mark.integration
MakeFake = Callable[[], FakeOllama]


def indexed(
    db_url: str, root: Path, fake: FakeOllama, body: Callable[[Harness], Awaitable[None]]
) -> None:
    async def scenario() -> None:
        async with ingest_harness(db_url, root, fake.url) as h:
            await reconcile(h.ctx, trigger="startup")
            await h.drain()
            await body(h)

    run_async(scenario())


def topic(name: str) -> list[float]:
    return fake_vector(f"topic:{name}")


def test_exact_identifier_found_by_text(
    db_url: str, tmp_path: Path, make_fake_ollama: MakeFake
) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("Projects/NAS.md", "# NAS\nHost nas01 has four disks.")
    vault.write("Other.md", "# Other\nUnrelated text.")

    async def body(h: Harness) -> None:
        async with h.pool.connection() as conn:
            result = await query(conn, "nas01", vector=fake_vector("unrelated query"))
        assert result.hits[0].path == "Projects/NAS.md"
        assert "text" in result.hits[0].matched
        assert (
            result.hits[0].headline is not None and "<mark>nas01</mark>" in result.hits[0].headline
        )

    indexed(db_url, tmp_path, fake, body)


def test_paraphrase_found_by_vector_only(
    db_url: str, tmp_path: Path, make_fake_ollama: MakeFake
) -> None:
    fake = make_fake_ollama()
    fake.behaviour.embed_topics = {"kopie zapasowe": "backup"}
    vault = VaultBuilder(tmp_path)
    vault.write("NAS.md", "# NAS\n## Kopie zapasowe\nCo noc o 02:00.")
    vault.write("Cats.md", "# Cats\nMeow.")

    async def body(h: Harness) -> None:
        async with h.pool.connection() as conn:
            result = await query(conn, "when do backups run", vector=topic("backup"))
        assert [hit.path for hit in result.hits][0] == "NAS.md"
        assert result.hits[0].matched == frozenset({"vector"})
        assert result.hits[0].headline is None
        assert result.hits[0].similarity is not None and result.hits[0].similarity > 0.99
        assert result.vector_used

    indexed(db_url, tmp_path, fake, body)


def test_both_lists_rank_first(db_url: str, tmp_path: Path, make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    fake.behaviour.embed_topics = {"raid": "disks"}
    vault = VaultBuilder(tmp_path)
    vault.write("Both.md", "# Both\nRAID 5 with four disks.")
    vault.write("TextOnly.md", "# TextOnly\nRAID mentioned once.")  # also 'raid' → same topic
    vault.write("Neither.md", "# Neither\nnothing")

    async def body(h: Harness) -> None:
        async with h.pool.connection() as conn:
            result = await query(conn, "four disks", vector=topic("disks"))
        assert result.hits[0].path == "Both.md"
        assert result.hits[0].matched == frozenset({"text", "vector"})

    indexed(db_url, tmp_path, fake, body)


def test_only_current_live_revisions_are_searched(
    db_url: str, tmp_path: Path, make_fake_ollama: MakeFake
) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("keep.md", "# Keep\nzebra current")
    vault.write("gone.md", "# Gone\nzebra deleted")

    async def body(h: Harness) -> None:
        vault.write("keep.md", "# Keep\nzebra pending edit")  # pending, not yet indexed
        vault.delete("gone.md")
        await reconcile(h.ctx, trigger="schedule")  # observes edit (pending), tombstones gone.md
        async with h.pool.connection() as conn:
            hits = (await query(conn, "zebra", vector=None)).hits
        assert [(hit.path, hit.content) for hit in hits] == [("keep.md", "zebra current")]

    indexed(db_url, tmp_path, fake, body)


def test_folder_and_tag_filters(db_url: str, tmp_path: Path, make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("Projects/a.md", "---\ntags: [homelab, nas]\n---\n# A\nzebra")
    vault.write("Projects/b.md", "---\ntags: [homelab]\n---\n# B\nzebra")
    vault.write("100%_done/c.md", "# C\nzebra")
    vault.write("100x_done/d.md", "# D\nzebra")

    async def body(h: Harness) -> None:
        async with h.pool.connection() as conn:

            async def paths(folder: str | None = None, tags: Sequence[str] = ()) -> list[str]:
                result = await query(conn, "zebra", vector=None, folder=folder, tags=tags)
                return sorted(hit.path for hit in result.hits)

            assert await paths(folder="Projects") == ["Projects/a.md", "Projects/b.md"]
            assert await paths(tags=["homelab", "nas"]) == ["Projects/a.md"]
            assert await paths(folder="100%_done") == ["100%_done/c.md"]

    indexed(db_url, tmp_path, fake, body)


def test_headline_escapes_html(db_url: str, tmp_path: Path, make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    VaultBuilder(tmp_path).write("x.md", "# X\nzebra <script>alert(1)</script> & co")

    async def body(h: Harness) -> None:
        async with h.pool.connection() as conn:
            [hit] = (await query(conn, "zebra", vector=None)).hits
        assert hit.headline is not None
        assert "<script>" not in hit.headline and "&lt;script&gt;" in hit.headline
        assert "<mark>zebra</mark>" in hit.headline

    indexed(db_url, tmp_path, fake, body)


@pytest.mark.parametrize("q", ['"unbalanced', "-", "or", "a:*", "!x", "a & b | c", "'", "\\"])
def test_search_odd_query_syntax_never_errors(
    db_url: str, tmp_path: Path, make_fake_ollama: MakeFake, q: str
) -> None:
    fake = make_fake_ollama()
    VaultBuilder(tmp_path).write("x.md", "# X\nzebra")

    async def body(h: Harness) -> None:
        async with h.pool.connection() as conn:
            await query(conn, q, vector=None)  # must not raise

    indexed(db_url, tmp_path, fake, body)


def test_chat_mode_match_rule_and_two_per_note(
    db_url: str, tmp_path: Path, make_fake_ollama: MakeFake
) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    long_note = "# Big\n" + "\n\n".join(
        f"## S{i}\nkopie zapasowe NAS sekcja {i} " + "x " * 700 for i in range(4)
    )
    vault.write("Big.md", long_note)
    vault.write("OneWord.md", "# One\nThe kopie only.")
    vault.write("Ident.md", "# Ident\nhost nas01 here")

    async def body(h: Harness) -> None:
        async with h.pool.connection() as conn:
            terms = chat_terms("Kiedy są kopie zapasowe? Co z nas01?")
            result = await query(conn, "", vector=None, mode="chat", terms=terms, limit=16)
        paths = [hit.path for hit in result.hits]
        assert paths.count("Big.md") == 2  # capped at 2 chunks per note
        assert "Ident.md" in paths  # one identifier is enough
        assert "OneWord.md" not in paths  # one ordinary word is not

    indexed(db_url, tmp_path, fake, body)


def test_chat_rule_runs_on_the_top_or_matches_only(
    db_url: str, tmp_path: Path, make_fake_ollama: MakeFake, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("Dense.md", "# Dense\nkopie kopie kopie kopie kopie kopie")
    vault.write("Both.md", "# Both\nkopie " + "x " * 400 + "zapasowe")

    async def body(h: Harness) -> None:
        terms = chat_terms("kopie zapasowe")
        async with h.pool.connection() as conn:
            wide = await query(conn, "", vector=None, mode="chat", terms=terms, limit=16)
            assert [hit.path for hit in wide.hits] == ["Both.md"]
            monkeypatch.setattr("ai_second_brain.search.query.CHAT_TEXT_POOL", 1)
            narrow = await query(conn, "", vector=None, mode="chat", terms=terms, limit=16)
        assert narrow.hits == []  # Dense.md ranks first on OR, then fails the rule

    indexed(db_url, tmp_path, fake, body)

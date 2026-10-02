from pathlib import Path

import httpx2
import psycopg
import pytest
from psycopg.pq import TransactionStatus

from ai_second_brain.chat.providers.ollama import create_http_client
from ai_second_brain.eval.embedding import (
    ModelSpace,
    PreflightError,
    embed_space,
    model_digests,
    preflight,
    query_vectors,
)
from ai_second_brain.eval.queries import EvalConfigError
from ai_second_brain.eval.snapshot import snapshot
from ai_second_brain.knowledge.embed_text import embed_input
from ai_second_brain.knowledge.embedder import Embedder, EmbedError
from ai_second_brain.vault.reconcile import reconcile

from ..conftest import run_async
from ..fakes.ollama import fake_vector
from ..ingest_harness import FAST, ingest_harness
from ..vaults import VaultBuilder

pytestmark = pytest.mark.integration

IDLE = TransactionStatus.IDLE


def _noop(model: str, done: int, total: int) -> None:
    return None


async def _count(ev: psycopg.AsyncConnection, sql: str, *params: object) -> int:
    row = await (await ev.execute(sql, params)).fetchone()  # type: ignore[call-overload]
    await ev.rollback()
    assert row is not None
    return int(row[0])


def _write_notes(vault: VaultBuilder, count: int) -> None:
    for i in range(count):
        vault.write(f"n{i}.md", f"# Note {i}\nunique body number {i}")


def test_cache_reuse_edit_and_resume(  # type: ignore[no-untyped-def]
    db_url: str, eval_db_url: str, tmp_path: Path, make_fake_ollama
) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    _write_notes(vault, 3)

    async def scenario() -> None:
        async with create_http_client() as client:
            make = lambda model: Embedder(fake.url, model, None, client, FAST)  # noqa: E731
            space = (await preflight(make, ["m1"]))[0]
            assert space == ModelSpace("m1", 100, 1024)
            emb = make("m1")
            async with ingest_harness(db_url, tmp_path, fake.url) as h:
                await reconcile(h.ctx, trigger="startup")
                await h.drain()
                async with (
                    await psycopg.AsyncConnection.connect(db_url) as dev,
                    await psycopg.AsyncConnection.connect(eval_db_url) as ev,
                ):
                    await snapshot(dev, ev)
                    first = await embed_space(ev, emb, space, batch=2, progress=_noop)
                    assert first == 3
                    assert ev.info.transaction_status == IDLE
                    sql = "SELECT count(*) FROM chunk_embeddings WHERE space_id = 100"
                    assert await _count(ev, sql) == 3
                    calls = len(fake.embed_requests())
                    again = await embed_space(ev, emb, space, batch=2, progress=_noop)
                    assert again == 0
                    assert ev.info.transaction_status == IDLE
                    assert len(fake.embed_requests()) == calls
                    last = fake.embed_requests()[-1].body
                    assert last["keep_alive"] == "30m"
                    assert await _count(ev, sql) == 3
                    spaces = await (
                        await ev.execute("SELECT id, model, dims, is_default FROM embedding_spaces")
                    ).fetchall()
                    await ev.rollback()
                    assert (100, "m1", 1024, False) in spaces

                    vault.write("n1.md", "# Note 1\nedited body that is different")
                    await reconcile(h.ctx, trigger="schedule")
                    await h.drain()
                    await dev.rollback()
                    await snapshot(dev, ev)
                    edited = await embed_space(ev, emb, space, batch=2, progress=_noop)
                    assert edited == 1
                    assert await _count(ev, sql) == 3

    run_async(scenario())


def test_interrupted_embedding_resumes(  # type: ignore[no-untyped-def]
    db_url: str, eval_db_url: str, tmp_path: Path, make_fake_ollama
) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    _write_notes(vault, 5)

    async def scenario() -> None:
        async with create_http_client() as client:
            make = lambda model: Embedder(fake.url, model, None, client, FAST)  # noqa: E731
            space = (await preflight(make, ["m1"]))[0]
            emb = make("m1")
            async with ingest_harness(db_url, tmp_path, fake.url) as h:
                await reconcile(h.ctx, trigger="startup")
                await h.drain()
                async with (
                    await psycopg.AsyncConnection.connect(db_url) as dev,
                    await psycopg.AsyncConnection.connect(eval_db_url) as ev,
                ):
                    await snapshot(dev, ev)
                    base = len(fake.embed_requests())
                    fake.behaviour.embed_fail_on_call = base + 2
                    with pytest.raises(EmbedError):
                        await embed_space(ev, emb, space, batch=2, progress=_noop)
                    assert ev.info.transaction_status == IDLE
                    cache = "SELECT count(*) FROM eval_embedding_cache WHERE model = 'm1'"
                    assert await _count(ev, cache) == 2
                    fake.behaviour.embed_fail_on_call = None
                    assert await embed_space(ev, emb, space, batch=2, progress=_noop) == 3
                    assert ev.info.transaction_status == IDLE
                    assert await _count(ev, cache) == 5
                    sql = "SELECT count(*) FROM chunk_embeddings WHERE space_id = 100"
                    assert await _count(ev, sql) == 5

    run_async(scenario())


def test_preflight_missing_model(make_fake_ollama) -> None:  # type: ignore[no-untyped-def]
    fake = make_fake_ollama()
    fake.behaviour.missing_models = {"ghost"}

    async def scenario() -> None:
        async with create_http_client() as client:
            make = lambda model: Embedder(fake.url, model, None, client, FAST)  # noqa: E731
            with pytest.raises(PreflightError) as caught:
                await preflight(make, ["m1", "ghost"])
            assert (caught.value.code, caught.value.model) == ("embed_model_missing", "ghost")
            with pytest.raises(PreflightError) as cloud:
                await preflight(make, ["big:cloud"])
            assert cloud.value.code == "cloud_model_refused"

    run_async(scenario())


def test_query_vectors_and_latency(make_fake_ollama) -> None:  # type: ignore[no-untyped-def]
    fake = make_fake_ollama()

    async def scenario() -> None:
        async with create_http_client() as client:
            emb = Embedder(fake.url, "m1", None, client, FAST)
            vectors, ms = await query_vectors(emb, ["a", "b"])
            assert len(vectors) == 2 == len(ms)
            assert all(t >= 0 for t in ms)
            requests = fake.embed_requests()
            assert len(requests) == 3
            assert all(r.body["keep_alive"] == "30m" for r in requests)

    run_async(scenario())


def test_model_digests_unknown_when_unavailable(make_fake_ollama) -> None:  # type: ignore[no-untyped-def]
    fake = make_fake_ollama()

    async def scenario() -> None:
        async with httpx2.AsyncClient() as client:
            assert await model_digests(client, fake.url, ["m1"]) == {"m1": "unknown"}

    run_async(scenario())


def test_seed_space_survives_bge_m3_run_and_vectors_round_trip(  # type: ignore[no-untyped-def]
    db_url: str, eval_db_url: str, tmp_path: Path, make_fake_ollama
) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    _write_notes(vault, 2)

    async def scenario() -> None:
        async with create_http_client() as client:
            make = lambda model: Embedder(fake.url, model, None, client, FAST)  # noqa: E731
            space = (await preflight(make, ["bge-m3"]))[0]
            async with ingest_harness(db_url, tmp_path, fake.url) as h:
                await reconcile(h.ctx, trigger="startup")
                await h.drain()
                async with (
                    await psycopg.AsyncConnection.connect(db_url) as dev,
                    await psycopg.AsyncConnection.connect(eval_db_url) as ev,
                ):
                    await snapshot(dev, ev)
                    await embed_space(ev, make("bge-m3"), space, batch=8, progress=_noop)
                    rows = await (
                        await ev.execute("SELECT id, model, is_default FROM embedding_spaces")
                    ).fetchall()
                    await ev.rollback()
                    by_id = {r[0]: r for r in rows}
                    assert by_id[1][2] is True
                    assert by_id[100][1] == "bge-m3"
                    # round trip: stored vector matches the fake's vector for that input
                    stored = await (
                        await ev.execute(
                            "SELECT e.embedding::text, s.title, c.heading_path, c.content"
                            " FROM chunk_embeddings e JOIN chunks c ON c.id = e.chunk_id"
                            " JOIN sources s ON s.current_revision_id = c.revision_id"
                            " WHERE e.space_id = 100"
                        )
                    ).fetchall()
                    await ev.rollback()
                    assert len(stored) == 2
                    for text, title, heading_path, content in stored:
                        got = [float(x) for x in text.strip("[]").split(",")]
                        want = fake_vector(embed_input(title or "", heading_path, content))
                        assert len(got) == len(want)
                        assert max(abs(a - b) for a, b in zip(got, want, strict=True)) < 1e-3

    run_async(scenario())


def test_embed_space_requires_prepared_database(  # type: ignore[no-untyped-def]
    db_url: str, make_fake_ollama
) -> None:
    fake = make_fake_ollama()

    async def scenario() -> None:
        async with create_http_client() as client:
            emb = Embedder(fake.url, "m1", None, client, FAST)
            async with await psycopg.AsyncConnection.connect(db_url) as dev:
                with pytest.raises(EvalConfigError):
                    await embed_space(
                        dev, emb, ModelSpace("m1", 100, 1024), batch=2, progress=_noop
                    )
                assert fake.embed_requests() == []

    run_async(scenario())


def test_duplicate_inputs_embedded_once_and_dims_checked(  # type: ignore[no-untyped-def]
    db_url: str, eval_db_url: str, tmp_path: Path, make_fake_ollama
) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("a/same.md", "# Same\nidentical body")
    vault.write("b/same.md", "# Same\nidentical body")

    async def scenario() -> None:
        async with create_http_client() as client:
            make = lambda model: Embedder(fake.url, model, None, client, FAST)  # noqa: E731
            space = (await preflight(make, ["m1"]))[0]
            async with ingest_harness(db_url, tmp_path, fake.url) as h:
                await reconcile(h.ctx, trigger="startup")
                await h.drain()
                async with (
                    await psycopg.AsyncConnection.connect(db_url) as dev,
                    await psycopg.AsyncConnection.connect(eval_db_url) as ev,
                ):
                    await snapshot(dev, ev)
                    base = len(fake.embed_requests())
                    wrong = ModelSpace("m1", 100, 512)
                    with pytest.raises(EmbedError) as caught:
                        await embed_space(ev, make("m1"), wrong, batch=8, progress=_noop)
                    assert caught.value.code == "embed_bad_response"
                    cache = "SELECT count(*) FROM eval_embedding_cache"
                    assert await _count(ev, cache) == 0
                    fake.requests.clear()
                    assert await embed_space(ev, make("m1"), space, batch=8, progress=_noop) == 1
                    sent = [t for r in fake.embed_requests() for t in r.body["input"]]
                    assert len(sent) == 1
                    sql = "SELECT count(*) FROM chunk_embeddings WHERE space_id = 100"
                    assert await _count(ev, sql) == 2
                    assert base >= 0

    run_async(scenario())

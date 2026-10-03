from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from psycopg import AsyncConnection

from ai_second_brain.graph import store
from ai_second_brain.graph.names import norm
from ai_second_brain.vault.observe import observe

from ..conftest import run_async
from ..fakes.ollama import fake_vector
from ..ingest_harness import Harness, ingest_harness
from ..vaults import VaultBuilder

pytestmark = pytest.mark.integration

DIMS = 1024


def run(
    db_url: str, root: Path, body: Callable[[Harness, AsyncConnection], Awaitable[None]]
) -> None:
    async def scenario() -> None:
        async with ingest_harness(db_url, root, None) as h:
            await h.rows("TRUNCATE entities CASCADE")
            async with h.pool.connection() as conn:
                await conn.set_autocommit(True)
                await body(h, conn)

    run_async(scenario())


async def index(h: Harness, path: str) -> UUID:
    await observe(h.ctx, path)
    await h.drain()
    [row] = await h.rows(
        "SELECT current_revision_id AS r FROM sources WHERE external_ref = %s", path
    )
    return row["r"]


def test_create_and_find_by_name_and_alias(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness, conn: AsyncConnection) -> None:
        e = await store.create_entity(conn, "device", "  NAS  Box ", ["nas01", "NAS01", "nas box"])
        assert e.status == "proposed" and e.type == "device"
        hit = await store.find_by_name(conn, "device", norm("NAS Box"))
        assert hit is not None and hit[1] == "exact" and hit[0].id == e.id
        hit = await store.find_by_name(conn, "device", norm("NAS01"))
        assert hit is not None and hit[1] == "alias" and hit[0].id == e.id
        assert await store.find_by_name(conn, "tool", norm("NAS01")) is None
        assert await store.find_by_name(conn, "device", "nope") is None
        aliases = await h.rows("SELECT alias FROM entity_aliases")
        assert [a["alias"] for a in aliases] == ["nas01"]

    run(db_url, tmp_path, body)


def test_create_entity_skips_existing_alias(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness, conn: AsyncConnection) -> None:
        first = await store.create_entity(conn, "tool", "Postgres", ["pg"])
        second = await store.create_entity(conn, "tool", "PostgreSQL", ["PG", "psql"])
        assert first.id != second.id
        hit = await store.find_by_name(conn, "tool", "pg")
        assert hit is not None and hit[0].id == first.id
        hit = await store.find_by_name(conn, "tool", "psql")
        assert hit is not None and hit[0].id == second.id
        # the same alias string is fine for another type
        other = await store.create_entity(conn, "topic", "Databases", ["pg"])
        hit = await store.find_by_name(conn, "topic", "pg")
        assert hit is not None and hit[0].id == other.id

    run(db_url, tmp_path, body)


def test_nearest_by_embedding(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness, conn: AsyncConnection) -> None:
        [space] = await h.rows("SELECT id FROM embedding_spaces WHERE is_default")
        sid = space["id"]
        a = await store.create_entity(conn, "device", "Alpha", [])
        b = await store.create_entity(conn, "device", "Beta", [])
        t = await store.create_entity(conn, "tool", "Gamma", [])
        assert await store.missing_embedding(conn, a.id, sid)
        for ent, text in ((a, "alpha"), (b, "beta"), (t, "alpha")):
            await store.upsert_entity_embedding(conn, ent.id, sid, fake_vector(text, DIMS))
        assert not await store.missing_embedding(conn, a.id, sid)
        await store.upsert_entity_embedding(conn, a.id, sid, fake_vector("alpha", DIMS))  # upsert

        async def near(text: str) -> tuple[store.EntityRow, float] | None:
            return await store.nearest_by_embedding(
                conn,
                "device",
                fake_vector(text, DIMS),
                space_id=sid,
                dims=DIMS,
                min_similarity=0.9,
            )

        hit = await near("alpha")
        assert hit is not None and hit[0].id == a.id and hit[1] > 0.99  # not the tool twin
        assert await near("unrelated") is None
        await conn.execute("UPDATE entities SET status = 'rejected' WHERE id = %s", (a.id,))
        assert await near("alpha") is None
        hit = await near("beta")
        assert hit is not None and hit[0].id == b.id

    run(db_url, tmp_path, body)


def test_extractions_upsert_and_per_version(db_url: str, tmp_path: Path) -> None:
    VaultBuilder(tmp_path).write("N.md", "# N\ntext\n")

    async def body(h: Harness, conn: AsyncConnection) -> None:
        rev = await index(h, "N.md")
        assert not await store.has_ok_extraction(conn, rev, "v1")
        await store.record_extraction(conn, rev, "v1", status="failed", model="m", error="boom")
        assert not await store.has_ok_extraction(conn, rev, "v1")
        await store.record_extraction(
            conn, rev, "v1", status="ok", model="m", summary="s", output={"a": 1}
        )
        await store.record_extraction(
            conn, rev, "v1", status="ok", model="m2", summary="s2", output={"a": 2}
        )
        rows = await h.rows("SELECT status, model, summary, output, error FROM extractions")
        assert len(rows) == 1
        assert rows[0]["model"] == "m2" and rows[0]["output"] == {"a": 2}
        assert rows[0]["error"] is None
        assert await store.has_ok_extraction(conn, rev, "v1")
        assert not await store.has_ok_extraction(conn, rev, "v2")

    run(db_url, tmp_path, body)


def test_revision_chunks_and_info(db_url: str, tmp_path: Path) -> None:
    VaultBuilder(tmp_path).write("Note.md", "# Top\nfirst body\n\n## Second\nsecond body\n")

    async def body(h: Harness, conn: AsyncConnection) -> None:
        rev = await index(h, "Note.md")
        got = await store.revision_chunks(conn, rev)
        expected = await h.rows(
            "SELECT id, heading_text, content FROM chunks WHERE revision_id = %s ORDER BY ordinal",
            rev,
        )
        assert len(got) >= 2
        assert got == [(r["id"], r["heading_text"], r["content"]) for r in expected]
        assert "first body" in got[0][2]

        info = await store.revision_info(conn, rev)
        assert info is not None and info.path == "Note.md" and info.is_current and info.live
        assert await store.revision_info(conn, uuid4()) is None

        await h.rows("UPDATE sources SET deleted_at = now()")
        info = await store.revision_info(conn, rev)
        assert info is not None and info.is_current and not info.live

        await h.rows("UPDATE sources SET current_revision_id = NULL")
        info = await store.revision_info(conn, rev)
        assert info is not None and not info.is_current

    run(db_url, tmp_path, body)

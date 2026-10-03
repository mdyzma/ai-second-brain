from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from psycopg import AsyncConnection

from ai_second_brain.graph import decide, store
from ai_second_brain.graph.context import GraphContext
from ai_second_brain.graph.decide import DecisionError
from ai_second_brain.graph.names import norm
from ai_second_brain.graph.resolve import resolve
from ai_second_brain.vault.observe import observe

from ..conftest import run_async
from ..fakes.queue import FakeQueue
from ..ingest_harness import Harness, ingest_harness
from ..vaults import VaultBuilder

pytestmark = pytest.mark.integration

PATH = "homelab.md"


def run(
    db_url: str, root: Path, body: Callable[[Harness, AsyncConnection], Awaitable[None]]
) -> None:
    VaultBuilder(root).write(PATH, "# Homelab\nThe NAS runs Proxmox.")

    async def scenario() -> None:
        async with ingest_harness(db_url, root, None) as h:
            await h.rows("TRUNCATE entities CASCADE")
            await observe(h.ctx, PATH)
            await h.drain()
            async with h.pool.connection() as conn:
                await conn.set_autocommit(True)
                await body(h, conn)

    run_async(scenario())


async def source(h: Harness) -> tuple[UUID, UUID]:
    [row] = await h.rows(
        "SELECT id, current_revision_id AS r FROM sources WHERE external_ref = %s", PATH
    )
    return row["id"], row["r"]


async def entity(
    conn: AsyncConnection,
    type_: str,
    name: str,
    status: str = "proposed",
    aliases: Sequence[str] = (),
) -> UUID:
    row = await store.create_entity(conn, type_, name, aliases)
    await conn.execute(
        "UPDATE entities SET status = %s::graph_status WHERE id = %s", (status, row.id)
    )
    return row.id


async def edge(
    conn: AsyncConnection,
    src_type: str,
    src_id: UUID,
    relation: str,
    dst: UUID,
    confidence: float = 0.9,
    status: str = "proposed",
    decided_by: str = "auto",
) -> UUID:
    cur = await conn.execute(
        "INSERT INTO edges (src_type, src_id, relation, dst_entity_id, confidence, origin,"
        " status, decided_by) VALUES (%s, %s, %s, %s, %s, 'llm:fake', %s::graph_status, %s)"
        " RETURNING id",
        (src_type, src_id, relation, dst, confidence, status, decided_by),
    )
    row = await cur.fetchone()
    assert row is not None
    return row[0]


async def edge_rows(h: Harness) -> dict[UUID, dict[str, Any]]:
    rows = await h.rows(
        "SELECT id, src_type, src_id, relation, dst_entity_id, status::text AS status,"
        " decided_by, confidence FROM edges"
    )
    return {r["id"]: r for r in rows}


async def ent_row(h: Harness, entity_id: UUID) -> dict[str, Any] | None:
    rows = await h.rows(
        "SELECT id, type::text AS type, name, norm_name, status::text AS status, parent_id,"
        " parent_status::text AS parent_status, reviewed_at FROM entities WHERE id = %s",
        entity_id,
    )
    return rows[0] if rows else None


async def aliases(h: Harness, entity_id: UUID) -> set[tuple[str, str]]:
    rows = await h.rows(
        "SELECT type::text AS type, norm_alias FROM entity_aliases WHERE entity_id = %s",
        entity_id,
    )
    return {(r["type"], r["norm_alias"]) for r in rows}


async def expect(code: str, call: Awaitable[Any], conn: AsyncConnection) -> None:
    with pytest.raises(DecisionError) as info:
        async with conn.transaction():
            await call
    assert info.value.code == code


def test_accept_accepts_confident_auto_edges_only(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness, conn: AsyncConnection) -> None:
        src, _rev = await source(h)
        nas = await entity(conn, "device", "NAS")
        box = await entity(conn, "device", "Box")
        other = await entity(conn, "tool", "Proxmox")
        sure = await edge(conn, "source", src, "mentions", nas, 0.5)
        unsure = await edge(conn, "source", src, "about", nas, 0.4)
        user_no = await edge(conn, "source", uuid4(), "mentions", nas, 0.9, "rejected", "user")
        between = await edge(conn, "entity", other, "runs_on", nas, 0.9)
        auto_rej = await edge(conn, "entity", nas, "works_with", box, 0.9, "rejected")
        async with conn.transaction():
            await decide.accept_entity(conn, nas)
        e = await ent_row(h, nas)
        assert e is not None and e["status"] == "accepted" and e["reviewed_at"] is not None
        got = await edge_rows(h)
        assert got[sure]["status"] == "accepted" and got[sure]["decided_by"] == "auto"
        assert got[unsure]["status"] == "proposed"
        assert got[user_no]["status"] == "rejected" and got[user_no]["decided_by"] == "user"
        assert got[between]["status"] == "proposed"  # entity-to-entity edges stay proposed
        assert got[auto_rej]["status"] == "proposed"  # an auto reject is undone by accept
        await expect("not_found", decide.accept_entity(conn, uuid4()), conn)

    run(db_url, tmp_path, body)


def test_reject_rejects_auto_edges_and_blocks_name(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness, conn: AsyncConnection) -> None:
        src, rev = await source(h)
        club = await entity(conn, "organization", "Tuesday Club")
        alice = await entity(conn, "person", "Alice", "accepted")
        into = await edge(conn, "source", src, "about", club, 0.9)
        out = await edge(conn, "entity", club, "works_with", alice, 0.9)
        kept = await edge(conn, "entity", alice, "works_with", club, 0.9, "accepted", "user")
        async with conn.transaction():
            await decide.reject_entity(conn, club)
        got = await edge_rows(h)
        assert got[into]["status"] == "rejected" and got[into]["decided_by"] == "auto"
        assert got[out]["status"] == "rejected"
        assert got[kept]["status"] == "accepted" and got[kept]["decided_by"] == "user"
        e = await ent_row(h, club)
        assert e is not None and e["status"] == "rejected"

        # Re-run resolution from the stored output: the rejected name is dropped.
        output = {
            "summary": "s",
            "entities": [
                {"name": "tuesday  club", "type": "organization", "aliases": [], "confidence": 1},
                {"name": "Alice", "type": "person", "aliases": [], "confidence": 0.9},
            ],
            "relations": [
                {
                    "subject": "NOTE",
                    "relation": "about",
                    "object": "tuesday  club",
                    "chunk": None,
                    "confidence": 0.9,
                },
            ],
        }
        await store.record_extraction(conn, rev, "4a.1", status="ok", model="fake", output=output)
        [stored] = await h.rows("SELECT output FROM extractions WHERE revision_id = %s", rev)
        ctx = GraphContext(h.pool, h.ctx.settings, None, None, FakeQueue())
        async with conn.transaction():
            counts = await resolve(
                conn, ctx, source_id=src, revision_id=rev, output=stored["output"]
            )
        assert counts.created == 0 and counts.dropped >= 1
        names = await h.rows("SELECT norm_name FROM entities ORDER BY norm_name")
        assert [r["norm_name"] for r in names] == ["alice", "tuesday club"]
        to_club = [r for r in (await edge_rows(h)).values() if r["dst_entity_id"] == club]
        assert all(r["status"] == "rejected" or r["decided_by"] == "user" for r in to_club)
        assert not any(r["src_type"] == "source" and r["status"] != "rejected" for r in to_club)

    run(db_url, tmp_path, body)


def test_rename_adds_old_name_as_alias_and_collision_is_name_taken(
    db_url: str, tmp_path: Path
) -> None:
    async def body(h: Harness, conn: AsyncConnection) -> None:
        pg = await entity(conn, "tool", "Postgres", aliases=["pg"])
        await entity(conn, "tool", "MySQL", aliases=["my"])
        await entity(conn, "topic", "PostgreSQL")  # another type: no clash
        async with conn.transaction():
            await decide.rename_entity(conn, pg, "  PostgreSQL ")
        e = await ent_row(h, pg)
        assert e is not None and e["name"] == "PostgreSQL" and e["norm_name"] == "postgresql"
        assert await aliases(h, pg) == {("tool", "pg"), ("tool", "postgres")}
        hit = await store.find_by_name(conn, "tool", norm("Postgres"))
        assert hit is not None and hit[0].id == pg and hit[1] == "alias"

        # Case-only change: no self alias.
        async with conn.transaction():
            await decide.rename_entity(conn, pg, "postgresql")
        assert await aliases(h, pg) == {("tool", "pg"), ("tool", "postgres")}
        # Renaming to one of its own aliases drops that alias row.
        async with conn.transaction():
            await decide.rename_entity(conn, pg, "PG")
        assert await aliases(h, pg) == {("tool", "postgres"), ("tool", "postgresql")}

        await expect("name_taken", decide.rename_entity(conn, pg, "mysql"), conn)
        await expect("name_taken", decide.rename_entity(conn, pg, "MY"), conn)
        await expect("invalid_action", decide.rename_entity(conn, pg, "   "), conn)
        await expect("invalid_action", decide.rename_entity(conn, pg, "x" * 201), conn)
        await expect("not_found", decide.rename_entity(conn, uuid4(), "y"), conn)
        e = await ent_row(h, pg)
        assert e is not None and e["name"] == "PG"

    run(db_url, tmp_path, body)


def test_retype_updates_alias_types_and_collision(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness, conn: AsyncConnection) -> None:
        nas = await entity(conn, "tool", "NAS", aliases=["nas01"])
        tool_parent = await entity(conn, "tool", "Storage")
        dev_parent = await entity(conn, "device", "Rack")
        await conn.execute(
            "UPDATE entities SET parent_id = %s, parent_status = 'accepted' WHERE id = %s",
            (tool_parent, nas),
        )
        async with conn.transaction():
            await decide.retype_entity(conn, nas, "device")
        e = await ent_row(h, nas)
        assert e is not None and e["type"] == "device"
        assert e["parent_id"] is None and e["parent_status"] is None  # parent was a tool
        assert await aliases(h, nas) == {("device", "nas01")}
        hit = await store.find_by_name(conn, "device", "nas01")
        assert hit is not None and hit[0].id == nas

        # Same-type parent survives a retype.
        await conn.execute(
            "UPDATE entities SET parent_id = %s, parent_status = 'accepted' WHERE id = %s",
            (dev_parent, nas),
        )
        await entity(conn, "topic", "Rack")  # rack clashes in topic
        async with conn.transaction():
            await decide.retype_entity(conn, dev_parent, "project")
        async with conn.transaction():
            await decide.retype_entity(conn, dev_parent, "device")
        async with conn.transaction():
            await decide.retype_entity(conn, nas, "device")  # no-op
        e = await ent_row(h, nas)
        assert e is not None and e["parent_id"] == dev_parent

        await expect("name_taken", decide.retype_entity(conn, dev_parent, "topic"), conn)
        await entity(conn, "project", "Thing", aliases=["NAS01"])
        await expect("name_taken", decide.retype_entity(conn, nas, "project"), conn)
        await expect("invalid_action", decide.retype_entity(conn, nas, "planet"), conn)
        e = await ent_row(h, nas)
        assert e is not None and e["type"] == "device"
        assert await aliases(h, nas) == {("device", "nas01")}

    run(db_url, tmp_path, body)


def test_set_parent_and_cycle(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness, conn: AsyncConnection) -> None:
        a = await entity(conn, "project", "A")
        b = await entity(conn, "project", "B")
        c = await entity(conn, "project", "C")
        person = await entity(conn, "person", "P")
        async with conn.transaction():
            await decide.set_parent(conn, b, a)
            await decide.set_parent(conn, c, b)
        e = await ent_row(h, c)
        assert e is not None and e["parent_id"] == b and e["parent_status"] == "accepted"
        await expect("parent_cycle", decide.set_parent(conn, a, c), conn)
        await expect("parent_cycle", decide.set_parent(conn, a, a), conn)
        await expect("type_mismatch", decide.set_parent(conn, a, person), conn)
        await expect("not_found", decide.set_parent(conn, a, uuid4()), conn)
        await expect("not_found", decide.set_parent(conn, uuid4(), a), conn)
        async with conn.transaction():
            await decide.set_parent(conn, c, None)
        e = await ent_row(h, c)
        assert e is not None and e["parent_id"] is None and e["parent_status"] is None
        async with conn.transaction():
            await decide.set_parent(conn, a, c)  # fine once the chain is broken
        e = await ent_row(h, a)
        assert e is not None and e["parent_id"] == c

    run(db_url, tmp_path, body)


def test_merge_collapses_duplicate_edges(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness, conn: AsyncConnection) -> None:
        src, _rev = await source(h)
        into = await entity(conn, "tool", "Postgres", "accepted", aliases=["pg"])
        loser = await entity(conn, "tool", "PostgreSQL", aliases=["psql", "Postgres DB"])
        other = await entity(conn, "device", "NAS")
        child = await entity(conn, "tool", "pgvector")
        mid = await entity(conn, "tool", "Mid")
        # into hangs under mid, mid under the loser: mid's link must not close a loop.
        for kid, parent in ((child, loser), (mid, loser), (into, mid)):
            await conn.execute(
                "UPDATE entities SET parent_id = %s, parent_status = 'proposed' WHERE id = %s",
                (parent, kid),
            )
        # The same note links both: the user's decision on into wins over auto 0.9.
        user_row = await edge(conn, "source", src, "mentions", into, 0.6, "accepted", "user")
        auto_dup = await edge(conn, "source", src, "mentions", loser, 0.9)
        # Without a user row the higher confidence wins.
        low = await edge(conn, "entity", other, "uses", into, 0.3)
        high = await edge(conn, "entity", other, "uses", loser, 0.8)
        # Both directions move; loser<->into edges become self-loops and go.
        outgoing = await edge(conn, "entity", loser, "runs_on", other, 0.7)
        loop1 = await edge(conn, "entity", loser, "works_with", into, 0.7)
        loop2 = await edge(conn, "entity", into, "part_of", loser, 0.7)
        [space] = await h.rows("SELECT id, dims FROM embedding_spaces WHERE is_default")
        await store.upsert_entity_embedding(conn, loser, space["id"], [0.1] * space["dims"])

        async with conn.transaction():
            assert await decide.merge_entities(conn, loser, into) == into

        assert await ent_row(h, loser) is None
        assert await h.rows("SELECT 1 FROM entity_embeddings WHERE entity_id = %s", loser) == []
        got = await edge_rows(h)
        assert set(got) == {user_row, high, outgoing}
        assert got[user_row]["status"] == "accepted" and got[user_row]["decided_by"] == "user"
        assert got[high]["dst_entity_id"] == into and got[high]["confidence"] == pytest.approx(0.8)
        assert got[outgoing]["src_id"] == into and got[outgoing]["dst_entity_id"] == other
        assert auto_dup not in got and low not in got and loop1 not in got and loop2 not in got
        assert not any(r["src_id"] == r["dst_entity_id"] for r in got.values())

        assert await aliases(h, into) == {
            ("tool", "pg"),
            ("tool", "postgresql"),
            ("tool", "psql"),
            ("tool", "postgres db"),
        }
        for name in ("PostgreSQL", "psql", "postgres db"):
            hit = await store.find_by_name(conn, "tool", norm(name))
            assert hit is not None and hit[0].id == into
        e_child, e_mid, e_into = [await ent_row(h, i) for i in (child, mid, into)]
        assert e_child is not None and e_child["parent_id"] == into
        assert e_mid is not None and e_mid["parent_id"] is None  # would have closed a loop
        assert e_into is not None and e_into["parent_id"] == mid

    run(db_url, tmp_path, body)


def test_merge_clears_into_parent_pointing_at_loser(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness, conn: AsyncConnection) -> None:
        into = await entity(conn, "tool", "Child")
        loser = await entity(conn, "tool", "Parent")
        await conn.execute(
            "UPDATE entities SET parent_id = %s, parent_status = 'accepted' WHERE id = %s",
            (loser, into),
        )
        async with conn.transaction():
            await decide.merge_entities(conn, loser, into)
        e = await ent_row(h, into)
        assert e is not None and e["parent_id"] is None and e["parent_status"] is None
        await expect("invalid_action", decide.merge_entities(conn, into, into), conn)
        await expect("not_found", decide.merge_entities(conn, uuid4(), into), conn)

    run(db_url, tmp_path, body)


def test_merge_type_mismatch(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness, conn: AsyncConnection) -> None:
        a = await entity(conn, "tool", "NAS")
        b = await entity(conn, "device", "NAS")
        await expect("type_mismatch", decide.merge_entities(conn, a, b), conn)
        assert await ent_row(h, a) is not None and await ent_row(h, b) is not None

    run(db_url, tmp_path, body)


def test_decide_links_batch(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness, conn: AsyncConnection) -> None:
        src, _rev = await source(h)
        nas = await entity(conn, "device", "NAS")
        box = await entity(conn, "device", "Box")
        one = await edge(conn, "source", src, "mentions", nas, 0.2)
        two = await edge(conn, "source", src, "mentions", box, 0.9, "accepted")
        three = await edge(conn, "entity", nas, "part_of", box, 0.9)
        async with conn.transaction():
            n = await decide.decide_links(
                conn, [(one, "accept"), (two, "reject"), (uuid4(), "accept"), (three, "accept")]
            )
        assert n == 3
        got = await edge_rows(h)
        assert got[one]["status"] == "accepted" and got[one]["decided_by"] == "user"
        assert got[two]["status"] == "rejected" and got[two]["decided_by"] == "user"
        assert got[three]["status"] == "accepted" and got[three]["decided_by"] == "user"
        assert await decide.decide_links(conn, []) == 0
        assert await decide.decide_links(conn, [(uuid4(), "reject")]) == 0

    run(db_url, tmp_path, body)

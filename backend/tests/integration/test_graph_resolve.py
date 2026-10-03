from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from psycopg.errors import DeadlockDetected
from psycopg_pool import AsyncConnectionPool

from ai_second_brain.chat.providers.ollama import create_http_client
from ai_second_brain.config import OllamaEndpointConfig
from ai_second_brain.graph import decide, store
from ai_second_brain.graph import extract as extract_module
from ai_second_brain.graph.context import GraphContext
from ai_second_brain.graph.extract import extract_revision
from ai_second_brain.graph.llm import ExtractClient
from ai_second_brain.graph.names import norm
from ai_second_brain.graph.queries import get_entity
from ai_second_brain.graph.resolve import resolve
from ai_second_brain.knowledge.embedder import Embedder
from ai_second_brain.search.embedding import QueryEmbedder
from ai_second_brain.vault.observe import observe

from ..conftest import run_async
from ..fakes.ollama import FakeOllama, fake_vector
from ..fakes.queue import FakeQueue
from ..ingest_harness import FAST, Harness, ingest_harness
from ..vaults import VaultBuilder

pytestmark = pytest.mark.integration

PATH = "homelab.md"
TITLE = "Homelab"
TEXT = "# Homelab\nThe NAS runs Proxmox."
DIMS = 1024
DOWN = "http://127.0.0.1:1"


def ent(
    name: str, type_: str, confidence: float = 0.9, aliases: Sequence[str] = ()
) -> dict[str, Any]:
    return {"name": name, "type": type_, "aliases": list(aliases), "confidence": confidence}


def rel(
    subject: str, relation: str, obj: str, chunk: str | None = "c1", c: float = 0.7
) -> dict[str, Any]:
    return {
        "subject": subject,
        "relation": relation,
        "object": obj,
        "chunk": chunk,
        "confidence": c,
    }


def reply(entities: list[dict[str, Any]], relations: list[dict[str, Any]]) -> dict[str, Any]:
    return {"summary": "Homelab notes.", "entities": entities, "relations": relations}


GOOD = reply(
    [ent("NAS", "device"), ent("Proxmox", "tool", 0.85)],
    [rel("NOTE", "about", "NAS", "c1", 0.9), rel("Proxmox", "runs_on", "NAS", "c1", 0.6)],
)


class CommitCheckingQueue(FakeQueue):
    """Records embed_entity and proves the entity is already committed when it is queued."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        super().__init__()
        self._pool = pool
        self.visible: list[bool] = []

    async def embed_entity(self, entity_id: UUID) -> None:
        async with self._pool.connection() as conn:
            cur = await conn.execute("SELECT 1 FROM entities WHERE id = %s", (entity_id,))
            self.visible.append(await cur.fetchone() is not None)
        await super().embed_entity(entity_id)


def calls(ctx: GraphContext) -> list[tuple[str, object]]:
    assert isinstance(ctx.queue, CommitCheckingQueue)
    return ctx.queue.calls


Body = Callable[[Harness, GraphContext, UUID], Awaitable[None]]


def scenario(
    db_url: str,
    root: Path,
    fake: FakeOllama,
    body: Body,
    *,
    embed_url: str | None = None,
) -> None:
    async def go() -> None:
        async with ingest_harness(db_url, root, None) as h:
            await h.rows("TRUNCATE entities CASCADE")
            await observe(h.ctx, PATH)
            await h.drain()
            [row] = await h.rows(
                "SELECT current_revision_id AS r FROM sources WHERE external_ref = %s", PATH
            )
            async with create_http_client() as http:
                endpoint = OllamaEndpointConfig(label="t", url=fake.url, model="fake")
                client = ExtractClient(http, [endpoint], "fake", FAST, 8192)
                names = None
                if embed_url is not None:
                    names = QueryEmbedder(Embedder(embed_url, "bge-m3", DIMS, http, FAST))
                queue = CommitCheckingQueue(h.pool)
                ctx = GraphContext(h.pool, h.ctx.settings, client, names, queue)
                await body(h, ctx, row["r"])

    run_async(go())


def vault(tmp_path: Path, text: str = TEXT) -> Path:
    VaultBuilder(tmp_path).write(PATH, text)
    return tmp_path


async def seed(
    h: Harness,
    type_: str,
    name: str,
    status: str = "accepted",
    aliases: Sequence[str] = (),
    vector_text: str | None = None,
) -> UUID:
    async with h.pool.connection() as conn:
        row = await store.create_entity(conn, type_, name, aliases)
        await conn.execute(
            "UPDATE entities SET status = %s::graph_status WHERE id = %s", (status, row.id)
        )
        if vector_text is not None:
            cur = await conn.execute("SELECT id FROM embedding_spaces WHERE is_default")
            space = await cur.fetchone()
            assert space is not None
            await store.upsert_entity_embedding(
                conn, row.id, space[0], fake_vector(vector_text, DIMS)
            )
    return row.id


async def edges(h: Harness) -> list[dict[str, Any]]:
    """Every edge, with readable endpoints: src is 'source' or the entity name."""
    return await h.rows(
        "SELECT CASE WHEN g.src_type = 'source' THEN 'source' ELSE s.name END AS src,"
        " g.relation, d.name AS dst, g.status::text AS status, g.decided_by, g.origin,"
        " g.confidence, g.evidence_chunk_id, g.revision_id, g.src_type, g.src_id,"
        " g.dst_entity_id"
        " FROM edges g JOIN entities d ON d.id = g.dst_entity_id"
        " LEFT JOIN entities s ON s.id = g.src_id AND g.src_type = 'entity'"
        " ORDER BY g.src_type DESC, src, g.relation, dst"
    )


def by_key(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    return {(r["src"], r["relation"], r["dst"]): r for r in rows}


async def entities(h: Harness) -> dict[str, dict[str, Any]]:
    rows = await h.rows(
        "SELECT id, name, type::text AS type, status::text AS status, parent_id,"
        " parent_status::text AS parent_status, attributes FROM entities"
    )
    return {r["name"]: r for r in rows}


async def edit(h: Harness, root: Path, text: str) -> UUID:
    VaultBuilder(root).write(PATH, text)
    await observe(h.ctx, PATH)
    await h.drain()
    [row] = await h.rows(
        "SELECT current_revision_id AS r FROM sources WHERE external_ref = %s", PATH
    )
    return row["r"]


async def source_id(h: Harness) -> UUID:
    [row] = await h.rows("SELECT id FROM sources WHERE external_ref = %s", PATH)
    return row["id"]


def test_new_entities_are_proposed_with_mention_and_about_edges(
    db_url: str, tmp_path: Path, make_fake_ollama: Callable[[], FakeOllama]
) -> None:
    fake = make_fake_ollama()
    fake.behaviour.chat_json_by_title = {TITLE: [GOOD]}

    async def body(h: Harness, ctx: GraphContext, rev: UUID) -> None:
        assert await extract_revision(ctx, rev) == "ok"
        ents = await entities(h)
        assert set(ents) == {"NAS", "Proxmox"}
        assert ents["NAS"]["type"] == "device" and ents["Proxmox"]["type"] == "tool"
        assert {e["status"] for e in ents.values()} == {"proposed"}
        [chunk] = await h.rows("SELECT id FROM chunks WHERE revision_id = %s", rev)
        sid = await source_id(h)
        got = by_key(await edges(h))
        assert set(got) == {
            ("source", "about", "NAS"),
            ("source", "mentions", "Proxmox"),
            ("Proxmox", "runs_on", "NAS"),
        }
        about = got[("source", "about", "NAS")]
        assert about["src_id"] == sid and about["evidence_chunk_id"] == chunk["id"]
        assert about["confidence"] == pytest.approx(0.9)  # the entity's confidence
        mention = got[("source", "mentions", "Proxmox")]
        assert mention["confidence"] == pytest.approx(0.85)
        runs_on = got[("Proxmox", "runs_on", "NAS")]
        assert runs_on["evidence_chunk_id"] == chunk["id"]
        assert runs_on["confidence"] == pytest.approx(0.6)
        for row in got.values():
            assert row["status"] == "proposed" and row["decided_by"] == "auto"
            assert row["origin"] == "llm:fake" and row["revision_id"] == rev

    scenario(db_url, vault(tmp_path), fake, body)


def test_exact_match_to_accepted_entity_auto_accepts_at_threshold(
    db_url: str, tmp_path: Path, make_fake_ollama: Callable[[], FakeOllama]
) -> None:
    fake = make_fake_ollama()
    fake.behaviour.chat_json_by_title = {
        TITLE: [
            reply(
                [ent("nas", "device", 0.8), ent("PROXMOX", "tool", 0.79)],
                [rel("Proxmox", "runs_on", "NAS", c=0.99)],
            )
        ]
    }

    async def body(h: Harness, ctx: GraphContext, rev: UUID) -> None:
        nas = await seed(h, "device", "NAS")
        proxmox = await seed(h, "tool", "Proxmox")
        assert await extract_revision(ctx, rev) == "ok"
        assert set(await entities(h)) == {"NAS", "Proxmox"}  # matched, nothing new
        got = by_key(await edges(h))
        accepted = got[("source", "mentions", "NAS")]
        assert accepted["status"] == "accepted" and accepted["decided_by"] == "auto"
        assert accepted["dst_entity_id"] == nas
        below = got[("source", "mentions", "Proxmox")]
        assert below["status"] == "proposed" and below["dst_entity_id"] == proxmox
        # entity-to-entity edges are never auto-accepted, even between accepted entities
        assert got[("Proxmox", "runs_on", "NAS")]["status"] == "proposed"
        assert calls(ctx) == []

    scenario(db_url, vault(tmp_path), fake, body)


def test_alias_match_counts_as_exact(
    db_url: str, tmp_path: Path, make_fake_ollama: Callable[[], FakeOllama]
) -> None:
    fake = make_fake_ollama()
    fake.behaviour.chat_json_by_title = {
        TITLE: [
            reply(
                [
                    ent("PVE", "tool", 0.9),  # the stored alias
                    ent("Network storage box", "device", 0.9, aliases=["nas01"]),  # own alias
                ],
                [],
            )
        ]
    }

    async def body(h: Harness, ctx: GraphContext, rev: UUID) -> None:
        proxmox = await seed(h, "tool", "Proxmox", aliases=["pve"])
        nas = await seed(h, "device", "NAS", aliases=["NAS01"])
        assert await extract_revision(ctx, rev) == "ok"
        assert set(await entities(h)) == {"NAS", "Proxmox"}
        got = by_key(await edges(h))
        assert set(got) == {("source", "mentions", "Proxmox"), ("source", "mentions", "NAS")}
        assert got[("source", "mentions", "Proxmox")]["dst_entity_id"] == proxmox
        assert got[("source", "mentions", "NAS")]["dst_entity_id"] == nas
        assert {r["status"] for r in got.values()} == {"accepted"}

    scenario(db_url, vault(tmp_path), fake, body)


def test_similar_name_links_as_proposed_with_suggested_alias(
    db_url: str, tmp_path: Path, make_fake_ollama: Callable[[], FakeOllama]
) -> None:
    fake = make_fake_ollama()
    fake.behaviour.embed_topics = {"proxmox": "pve"}
    fake.behaviour.chat_json_by_title = {
        TITLE: [
            reply([ent("Proxmox VE", "tool", 0.95)], []),
            reply([ent("Proxmox VE", "tool")], []),
        ]
    }

    async def body(h: Harness, ctx: GraphContext, rev: UUID) -> None:
        proxmox = await seed(h, "tool", "Proxmox", vector_text="topic:pve")
        assert await extract_revision(ctx, rev) == "ok"
        ents = await entities(h)
        assert set(ents) == {"Proxmox"}  # no new entity
        assert ents["Proxmox"]["attributes"]["suggested_aliases"] == ["Proxmox VE"]
        [edge] = await edges(h)
        assert edge["dst_entity_id"] == proxmox and edge["relation"] == "mentions"
        assert edge["status"] == "proposed"  # similar never auto-accepts
        embeds = [r.body["input"] for r in fake.embed_requests()]
        assert embeds == [["Proxmox VE"]]
        assert calls(ctx) == []
        # a second note revision suggesting the same name does not duplicate it
        rev2 = await edit(h, tmp_path, TEXT + "\nMore.")
        assert await extract_revision(ctx, rev2) == "ok"
        ents = await entities(h)
        assert ents["Proxmox"]["attributes"]["suggested_aliases"] == ["Proxmox VE"]

    scenario(db_url, vault(tmp_path), fake, body, embed_url=fake.url)


def test_suggested_aliases_are_capped(db_url: str, tmp_path: Path) -> None:
    async def go() -> None:
        async with ingest_harness(db_url, tmp_path, None) as h:
            await h.rows("TRUNCATE entities CASCADE")
            entity_id = await seed(h, "tool", "Proxmox")
            async with h.pool.connection() as conn:
                for i in range(12):
                    await store.add_suggested_alias(conn, entity_id, f"Proxmox {i}")
                await store.add_suggested_alias(conn, entity_id, "PROXMOX 0")
            [row] = await h.rows("SELECT attributes FROM entities")
            assert row["attributes"]["suggested_aliases"] == [f"Proxmox {i}" for i in range(10)]

    run_async(go())


def test_rejected_name_never_returns(
    db_url: str, tmp_path: Path, make_fake_ollama: Callable[[], FakeOllama]
) -> None:
    fake = make_fake_ollama()
    fake.behaviour.embed_topics = {"tuesday": "club"}
    fake.behaviour.chat_json_by_title = {
        TITLE: [
            reply(
                [
                    ent("Tuesday Club", "organization"),
                    ent("The Tuesday Crew", "organization", aliases=["tuesday club"]),
                    ent("Alice", "person"),
                ],
                [
                    rel("Alice", "works_with", "Tuesday Club"),
                    rel("Alice", "part_of", "The Tuesday Crew"),
                    rel("NOTE", "about", "Tuesday Club"),
                ],
            )
        ]
    }

    async def body(h: Harness, ctx: GraphContext, rev: UUID) -> None:
        club = await seed(h, "organization", "Tuesday Club", "rejected", vector_text="topic:club")
        assert await extract_revision(ctx, rev) == "ok"
        ents = await entities(h)
        assert set(ents) == {"Tuesday Club", "Alice"}  # no new entity for either name
        assert ents["Tuesday Club"]["status"] == "rejected"
        assert ents["Alice"]["parent_id"] is None  # the part_of relation was dropped
        got = await edges(h)
        assert [(r["src"], r["relation"], r["dst"]) for r in got] == [
            ("source", "mentions", "Alice")
        ]
        assert all(r["dst_entity_id"] != club for r in got)
        queued = [c for c in calls(ctx) if c[0] == "embed_entity"]
        assert queued == [("embed_entity", ents["Alice"]["id"])]

    scenario(db_url, vault(tmp_path), fake, body, embed_url=fake.url)


def test_user_decisions_survive_reextraction(
    db_url: str, tmp_path: Path, make_fake_ollama: Callable[[], FakeOllama]
) -> None:
    fake = make_fake_ollama()
    first = reply(
        [ent("NAS", "device"), ent("Proxmox", "tool"), ent("ZFS", "tool")],
        [
            rel("NOTE", "about", "NAS"),
            rel("Proxmox", "runs_on", "NAS"),
            rel("Proxmox", "uses", "ZFS"),
        ],
    )
    second = reply(
        [ent("NAS", "device", 0.6), ent("Proxmox", "tool", 0.5), ent("Ceph", "tool")],
        [rel("NOTE", "about", "NAS"), rel("Proxmox", "runs_on", "NAS", c=0.4)],
    )
    fake.behaviour.chat_json_by_title = {TITLE: [first, second]}

    async def body(h: Harness, ctx: GraphContext, rev: UUID) -> None:
        assert await extract_revision(ctx, rev) == "ok"
        await h.rows(
            "UPDATE edges SET status = 'accepted', decided_by = 'user' WHERE relation = 'about'"
        )
        await h.rows(
            "UPDATE edges SET status = 'rejected', decided_by = 'user' WHERE relation = 'runs_on'"
        )
        rev2 = await edit(h, tmp_path, TEXT + "\nNow with Ceph.")
        assert rev2 != rev
        assert await extract_revision(ctx, rev2) == "ok"
        got = by_key(await edges(h))
        assert set(got) == {
            ("source", "about", "NAS"),
            ("source", "mentions", "Proxmox"),
            ("source", "mentions", "Ceph"),
            ("Proxmox", "runs_on", "NAS"),
        }  # ZFS mention and Proxmox uses ZFS (machine rows of rev 1) are gone
        about = got[("source", "about", "NAS")]
        assert (about["status"], about["decided_by"]) == ("accepted", "user")
        assert about["confidence"] == pytest.approx(0.6) and about["revision_id"] == rev2
        runs_on = got[("Proxmox", "runs_on", "NAS")]
        assert (runs_on["status"], runs_on["decided_by"]) == ("rejected", "user")
        assert runs_on["confidence"] == pytest.approx(0.4)
        for key in (("source", "mentions", "Proxmox"), ("source", "mentions", "Ceph")):
            assert got[key]["decided_by"] == "auto" and got[key]["revision_id"] == rev2
        assert "ZFS" in await entities(h)  # entities are never deleted by extraction

    scenario(db_url, vault(tmp_path), fake, body)


def test_user_rejected_edge_stays_when_model_repeats_it(
    db_url: str, tmp_path: Path, make_fake_ollama: Callable[[], FakeOllama]
) -> None:
    fake = make_fake_ollama()
    again = reply([ent("NAS", "device", 0.95)], [])
    fake.behaviour.chat_json_by_title = {TITLE: [again, again]}

    async def body(h: Harness, ctx: GraphContext, rev: UUID) -> None:
        await seed(h, "device", "NAS")
        assert await extract_revision(ctx, rev) == "ok"
        [edge] = await edges(h)
        assert edge["status"] == "accepted" and edge["decided_by"] == "auto"
        await h.rows("UPDATE edges SET status = 'rejected', decided_by = 'user'")
        rev2 = await edit(h, tmp_path, TEXT + "\nedited")
        assert await extract_revision(ctx, rev2) == "ok"
        [edge] = await edges(h)
        assert (edge["status"], edge["decided_by"]) == ("rejected", "user")

    scenario(db_url, vault(tmp_path), fake, body)


def test_part_of_sets_proposed_parent_once(
    db_url: str, tmp_path: Path, make_fake_ollama: Callable[[], FakeOllama]
) -> None:
    fake = make_fake_ollama()
    first = reply(
        [ent("Media server", "project"), ent("Homelab rack", "project")],
        [rel("Media server", "part_of", "Homelab rack")],
    )
    second = reply(
        [ent("Media server", "project"), ent("Garage", "project")],
        [rel("Media server", "part_of", "Garage"), rel("Garage", "part_of", "Media server")],
    )
    fake.behaviour.chat_json_by_title = {TITLE: [first, second]}

    async def body(h: Harness, ctx: GraphContext, rev: UUID) -> None:
        assert await extract_revision(ctx, rev) == "ok"
        ents = await entities(h)
        media = ents["Media server"]
        assert media["parent_id"] == ents["Homelab rack"]["id"]
        assert media["parent_status"] == "proposed"
        assert ents["Homelab rack"]["parent_id"] is None
        rev2 = await edit(h, tmp_path, TEXT + "\nThe garage.")
        assert await extract_revision(ctx, rev2) == "ok"
        ents = await entities(h)
        assert ents["Media server"]["parent_id"] == ents["Homelab rack"]["id"]  # unchanged
        # Garage part_of Media server is fine: Media server's parent is not Garage
        assert ents["Garage"]["parent_id"] == ents["Media server"]["id"]
        got = by_key(await edges(h))
        assert got[("Media server", "part_of", "Garage")]["status"] == "proposed"

    scenario(db_url, vault(tmp_path), fake, body)


def test_new_entity_queues_name_embedding(
    db_url: str, tmp_path: Path, make_fake_ollama: Callable[[], FakeOllama]
) -> None:
    fake = make_fake_ollama()
    fake.behaviour.chat_json_by_title = {TITLE: [GOOD]}

    async def body(h: Harness, ctx: GraphContext, rev: UUID) -> None:
        nas = await seed(h, "device", "NAS")
        assert await extract_revision(ctx, rev) == "ok"
        ents = await entities(h)
        queue = ctx.queue
        assert isinstance(queue, CommitCheckingQueue)
        assert queue.calls == [("embed_entity", ents["Proxmox"]["id"])]  # not the existing NAS
        assert ents["NAS"]["id"] == nas
        assert queue.visible == [True]  # queued only after the commit

    scenario(db_url, vault(tmp_path), fake, body)


def test_embedder_down_skips_similarity_step(
    db_url: str, tmp_path: Path, make_fake_ollama: Callable[[], FakeOllama]
) -> None:
    fake = make_fake_ollama()
    fake.behaviour.chat_json_by_title = {TITLE: [reply([ent("Proxmox VE", "tool")], [])]}

    async def body(h: Harness, ctx: GraphContext, rev: UUID) -> None:
        await seed(h, "tool", "Proxmox", vector_text="topic:pve")
        assert await extract_revision(ctx, rev) == "ok"
        ents = await entities(h)
        assert set(ents) == {"Proxmox", "Proxmox VE"}  # created, not linked as similar
        assert ents["Proxmox"]["attributes"] == {}
        [edge] = await edges(h)
        assert edge["dst"] == "Proxmox VE" and edge["status"] == "proposed"

    scenario(db_url, vault(tmp_path), fake, body, embed_url=DOWN)


def test_no_names_embedder_skips_similarity_step(
    db_url: str, tmp_path: Path, make_fake_ollama: Callable[[], FakeOllama]
) -> None:
    fake = make_fake_ollama()
    fake.behaviour.embed_topics = {"proxmox": "pve"}
    fake.behaviour.chat_json_by_title = {TITLE: [reply([ent("Proxmox VE", "tool")], [])]}

    async def body(h: Harness, ctx: GraphContext, rev: UUID) -> None:
        await seed(h, "tool", "Proxmox", vector_text="topic:pve")
        assert ctx.names is None
        assert await extract_revision(ctx, rev) == "ok"
        assert set(await entities(h)) == {"Proxmox", "Proxmox VE"}
        assert fake.embed_requests() == []

    scenario(db_url, vault(tmp_path), fake, body)


def test_stale_revision_resolves_nothing(
    db_url: str, tmp_path: Path, make_fake_ollama: Callable[[], FakeOllama]
) -> None:
    fake = make_fake_ollama()
    fake.behaviour.chat_json_by_title = {TITLE: [GOOD]}

    async def body(h: Harness, ctx: GraphContext, rev: UUID) -> None:
        await edit(h, tmp_path, TEXT + "\nnewer")
        assert await extract_revision(ctx, rev) == "skipped"
        assert await entities(h) == {}
        assert await edges(h) == []
        assert calls(ctx) == []

    scenario(db_url, vault(tmp_path), fake, body)


def test_resolution_logs_carry_no_names(
    db_url: str,
    tmp_path: Path,
    make_fake_ollama: Callable[[], FakeOllama],
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = make_fake_ollama()
    fake.behaviour.chat_json_by_title = {TITLE: [GOOD]}

    async def body(h: Harness, ctx: GraphContext, rev: UUID) -> None:
        with caplog.at_level("DEBUG", logger="ai_second_brain"):
            assert await extract_revision(ctx, rev) == "ok"
        text = caplog.text
        assert "created=2" in text and "proposed=3" in text
        for name in ("NAS", "Proxmox", norm("Proxmox")):
            assert name not in text

    scenario(db_url, vault(tmp_path), fake, body)


def test_resolve_order_is_deterministic(
    db_url: str,
    tmp_path: Path,
    make_fake_ollama: Callable[[], FakeOllama],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = make_fake_ollama()
    scrambled = reply(
        [
            ent("Zeta", "tool"),
            ent("Rack", "device"),
            ent("alpha", "tool"),
            ent("Beta", "tool"),
            ent("Attic", "device"),
        ],
        [
            rel("Zeta", "runs_on", "Rack"),
            rel("Beta", "part_of", "Zeta"),
            rel("alpha", "runs_on", "Attic"),
            rel("Zeta", "works_with", "alpha"),
            rel("NOTE", "about", "Rack"),
            rel("alpha", "part_of", "Beta"),
        ],
    )
    fake.behaviour.chat_json_by_title = {TITLE: [scrambled]}
    created: list[tuple[str, str]] = []
    upserts: list[tuple[str, UUID, str, UUID]] = []
    parents: list[tuple[UUID, UUID]] = []
    real_create, real_upsert = store.create_entity, store.upsert_edge
    real_parent = store.set_proposed_parent

    async def create_entity(conn: Any, type_: str, name: str, aliases: Any) -> Any:
        created.append((type_, norm(name)))
        return await real_create(conn, type_, name, aliases)

    async def upsert_edge(conn: Any, **kw: Any) -> None:
        upserts.append((kw["src_type"], kw["src_id"], kw["relation"], kw["dst_entity_id"]))
        await real_upsert(conn, **kw)

    async def set_proposed_parent(conn: Any, child: UUID, parent: UUID) -> None:
        parents.append((child, parent))
        await real_parent(conn, child, parent)

    monkeypatch.setattr(store, "create_entity", create_entity)
    monkeypatch.setattr(store, "upsert_edge", upsert_edge)
    monkeypatch.setattr(store, "set_proposed_parent", set_proposed_parent)

    async def body(h: Harness, ctx: GraphContext, rev: UUID) -> None:
        assert await extract_revision(ctx, rev) == "ok"
        assert created == sorted(created)  # (type, norm(name)), not model-output order
        assert created[0] == ("device", "attic") and len(created) == 5
        assert len(upserts) == 5 + 5  # five entity links, five mention edges
        assert upserts == sorted(upserts)  # (src_type, src_id, relation, dst_entity_id)
        assert upserts[0][0] == "entity" and upserts[-1][0] == "source"
        assert parents == sorted(parents) and len(parents) == 2

    scenario(db_url, vault(tmp_path), fake, body)


class _Flaky:
    """Wraps extract._finish: does the real work, then raises on the first `fail` calls."""

    def __init__(self, real: Any, fail: int) -> None:
        self.real, self.fail, self.calls = real, fail, 0

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        result = await self.real(*args, **kwargs)
        if self.calls <= self.fail:
            raise DeadlockDetected("simulated deadlock")
        return result


def test_deadlock_retries_the_write_once_without_calling_the_model_again(
    db_url: str,
    tmp_path: Path,
    make_fake_ollama: Callable[[], FakeOllama],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = make_fake_ollama()
    fake.behaviour.chat_json_by_title = {TITLE: [GOOD, GOOD]}
    flaky = _Flaky(extract_module._finish, fail=1)
    monkeypatch.setattr(extract_module, "_finish", flaky)

    async def body(h: Harness, ctx: GraphContext, rev: UUID) -> None:
        assert await extract_revision(ctx, rev) == "ok"
        assert flaky.calls == 2
        assert len(fake.behaviour.chat_json_requests) == 1  # the model is not called again
        ents = await entities(h)
        assert set(ents) == {"NAS", "Proxmox"}
        assert len(await edges(h)) == 3
        [row] = await h.rows("SELECT status FROM extractions")
        assert row["status"] == "ok"
        expected = {("embed_entity", ents["NAS"]["id"]), ("embed_entity", ents["Proxmox"]["id"])}
        assert len(calls(ctx)) == 2 and set(calls(ctx)) == expected  # committed attempt only

    scenario(db_url, vault(tmp_path), fake, body)


def test_second_deadlock_raises_and_writes_nothing(
    db_url: str,
    tmp_path: Path,
    make_fake_ollama: Callable[[], FakeOllama],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = make_fake_ollama()
    fake.behaviour.chat_json_by_title = {TITLE: [GOOD, GOOD]}
    flaky = _Flaky(extract_module._finish, fail=2)
    monkeypatch.setattr(extract_module, "_finish", flaky)

    async def body(h: Harness, ctx: GraphContext, rev: UUID) -> None:
        with pytest.raises(DeadlockDetected):
            await extract_revision(ctx, rev)
        assert flaky.calls == 2
        assert len(fake.behaviour.chat_json_requests) == 1
        assert await h.rows("SELECT 1 FROM extractions") == []
        assert await entities(h) == {}
        assert await edges(h) == []
        assert calls(ctx) == []

    scenario(db_url, vault(tmp_path), fake, body)


def test_lost_create_race_counts_as_exact_link(
    db_url: str,
    tmp_path: Path,
    make_fake_ollama: Callable[[], FakeOllama],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = make_fake_ollama()
    fake.behaviour.chat_json_by_title = {TITLE: [reply([ent("NAS", "device", 0.9)], [])]}

    async def body(h: Harness, ctx: GraphContext, rev: UUID) -> None:
        nas = await seed(h, "device", "NAS")

        async def not_found(*_: Any) -> None:
            return None  # as if a concurrent note created NAS after our lookup

        monkeypatch.setattr(store, "find_by_name", not_found)
        assert await extract_revision(ctx, rev) == "ok"
        [edge] = await edges(h)
        assert edge["dst_entity_id"] == nas
        assert edge["status"] == "accepted"  # exact match to an accepted entity
        assert calls(ctx) == []  # no redundant embed job

    scenario(db_url, vault(tmp_path), fake, body)


def test_relation_naming_an_alias_resolves(db_url: str, tmp_path: Path) -> None:
    async def go() -> None:
        async with ingest_harness(db_url, vault(tmp_path), None) as h:
            await h.rows("TRUNCATE entities CASCADE")
            await observe(h.ctx, PATH)
            await h.drain()
            [row] = await h.rows(
                "SELECT id, current_revision_id AS r FROM sources WHERE external_ref = %s", PATH
            )
            await seed(h, "organization", "Tuesday Club", "rejected")
            output = reply(
                [
                    ent("Proxmox", "tool", aliases=["PVE"]),
                    ent("NAS", "device"),
                    ent("Alice", "person"),
                    ent("The Crew", "organization", aliases=["Tuesday Club"]),
                ],
                [
                    rel("PVE", "runs_on", "NAS"),
                    rel("Alice", "works_with", "Tuesday Club"),  # alias of a rejected hit
                ],
            )
            ctx = GraphContext(h.pool, h.ctx.settings, None, None, CommitCheckingQueue(h.pool))
            async with h.pool.connection() as conn:
                counts = await resolve(
                    conn, ctx, source_id=row["id"], revision_id=row["r"], output=output
                )
            assert counts.dropped == 2  # the dropped mention and the relation naming it
            got = by_key(await edges(h))
            assert ("Proxmox", "runs_on", "NAS") in got
            assert not any(k[0] == "Alice" for k in got)
            assert "The Crew" not in await entities(h)

    run_async(go())


def test_self_loop_relation_is_dropped(
    db_url: str, tmp_path: Path, make_fake_ollama: Callable[[], FakeOllama]
) -> None:
    fake = make_fake_ollama()
    fake.behaviour.chat_json_by_title = {
        TITLE: [
            reply(
                [ent("Proxmox", "tool"), ent("PVE", "tool")],
                [rel("Proxmox", "runs_on", "PVE"), rel("PVE", "part_of", "Proxmox")],
            )
        ]
    }

    async def body(h: Harness, ctx: GraphContext, rev: UUID) -> None:
        proxmox = await seed(h, "tool", "Proxmox", aliases=["pve"])
        assert await extract_revision(ctx, rev) == "ok"
        [edge] = await edges(h)  # one mention edge; both names are the same entity
        assert edge["src_type"] == "source" and edge["dst_entity_id"] == proxmox
        assert (await entities(h))["Proxmox"]["parent_id"] is None

    scenario(db_url, vault(tmp_path), fake, body)


async def entity_page_notes(h: Harness, entity_id: UUID) -> list[str]:
    async with h.pool.connection() as conn:
        page = await get_entity(conn, entity_id, vault_name="vault")
    assert page is not None
    return [n["path"] for n in page["notes"]]


def test_entity_accept_survives_reextraction(
    db_url: str, tmp_path: Path, make_fake_ollama: Callable[[], FakeOllama]
) -> None:
    fake = make_fake_ollama()
    fake.behaviour.embed_topics = {"proxmox": "pve"}
    mentions = reply(
        [ent("ZFS", "tool", 0.6), ent("NAS", "device", 0.9), ent("Proxmox VE", "tool")],
        [rel("ZFS", "runs_on", "NAS")],
    )
    gone = reply([ent("NAS", "device", 0.9)], [])
    fake.behaviour.chat_json_by_title = {TITLE: [mentions, mentions, gone]}

    async def body(h: Harness, ctx: GraphContext, rev: UUID) -> None:
        pve = await seed(h, "tool", "PVE", "proposed", vector_text="topic:pve")
        assert await extract_revision(ctx, rev) == "ok"
        ents = await entities(h)
        assert set(ents) == {"PVE", "ZFS", "NAS"}  # "Proxmox VE" is a similar match
        zfs, nas = ents["ZFS"]["id"], ents["NAS"]["id"]
        async with h.pool.connection() as conn:
            for entity_id in (zfs, nas, pve):
                await decide.accept_entity(conn, entity_id)
        # An accepted automatic relation edge (only a kept re-creation produces one).
        await h.rows("UPDATE edges SET status = 'accepted' WHERE relation = 'runs_on'")
        got = by_key(await edges(h))
        assert got[("source", "mentions", "ZFS")]["status"] == "accepted"  # at 0.6
        assert got[("source", "mentions", "PVE")]["status"] == "accepted"  # similar match
        assert await entity_page_notes(h, zfs) == [PATH]

        rev2 = await edit(h, tmp_path, TEXT + "\nTypo fixed.")
        assert await extract_revision(ctx, rev2) == "ok"
        got = by_key(await edges(h))
        for key in (
            ("source", "mentions", "ZFS"),
            ("source", "mentions", "PVE"),
            ("ZFS", "runs_on", "NAS"),
        ):
            row = got[key]
            assert (row["status"], row["decided_by"]) == ("accepted", "auto"), key
            assert row["revision_id"] == rev2
        assert await entity_page_notes(h, zfs) == [PATH]
        assert await entity_page_notes(h, pve) == [PATH]

        # A version that no longer mentions them drops the edges.
        rev3 = await edit(h, tmp_path, "# Homelab\nOnly the NAS now.")
        assert await extract_revision(ctx, rev3) == "ok"
        assert set(by_key(await edges(h))) == {("source", "mentions", "NAS")}
        assert await entity_page_notes(h, zfs) == []

    scenario(db_url, vault(tmp_path), fake, body, embed_url=fake.url)


def test_reextraction_keeps_accepted_only_while_the_entity_is_accepted(
    db_url: str, tmp_path: Path, make_fake_ollama: Callable[[], FakeOllama]
) -> None:
    fake = make_fake_ollama()
    out = reply([ent("Proxmox", "tool", 0.6), ent("NAS", "device", 0.6)], [])
    fake.behaviour.chat_json_by_title = {TITLE: [out, out]}

    async def body(h: Harness, ctx: GraphContext, rev: UUID) -> None:
        assert await extract_revision(ctx, rev) == "ok"
        ents = await entities(h)
        proxmox = ents["Proxmox"]["id"]
        async with h.pool.connection() as conn:
            await decide.accept_entity(conn, proxmox)
        # The edge was accepted, then the entity went back to proposed.
        await h.rows("UPDATE entities SET status = 'proposed' WHERE id = %s", proxmox)
        rev2 = await edit(h, tmp_path, TEXT + "\nedited")
        assert await extract_revision(ctx, rev2) == "ok"
        got = by_key(await edges(h))
        assert got[("source", "mentions", "Proxmox")]["status"] == "proposed"
        assert got[("source", "mentions", "NAS")]["status"] == "proposed"

    scenario(db_url, vault(tmp_path), fake, body)


def test_retype_survives_reextraction_with_the_old_type(
    db_url: str, tmp_path: Path, make_fake_ollama: Callable[[], FakeOllama]
) -> None:
    fake = make_fake_ollama()
    first = reply([ent("NAS", "tool", 0.9, aliases=["nas01"])], [])
    again = reply([ent("NAS", "tool", 0.9)], [])
    old_alias = reply([ent("nas01", "tool", 0.9)], [])
    fake.behaviour.chat_json_by_title = {TITLE: [first, again, old_alias]}

    async def body(h: Harness, ctx: GraphContext, rev: UUID) -> None:
        assert await extract_revision(ctx, rev) == "ok"
        nas = (await entities(h))["NAS"]["id"]
        async with h.pool.connection() as conn:
            await decide.retype_entity(conn, nas, "device")
            await decide.accept_entity(conn, nas)
        for suffix in ("\nedited", "\nedited again"):
            rev_n = await edit(h, tmp_path, TEXT + suffix)
            assert await extract_revision(ctx, rev_n) == "ok"
            ents = await entities(h)
            assert set(ents) == {"NAS"} and ents["NAS"]["type"] == "device"  # no duplicate
            [edge] = await edges(h)
            assert edge["dst_entity_id"] == nas and edge["status"] == "accepted"
            assert await entity_page_notes(h, nas) == [PATH]
        async with h.pool.connection() as conn:
            page = await get_entity(conn, nas, vault_name="vault")
        assert page is not None and page["aliases"] == ["nas01"]  # the name is not shown

    scenario(db_url, vault(tmp_path), fake, body)


def test_relation_endpoints_are_matched_by_type(db_url: str, tmp_path: Path) -> None:
    async def go() -> None:
        async with ingest_harness(db_url, vault(tmp_path), None) as h:
            await h.rows("TRUNCATE entities CASCADE")
            await observe(h.ctx, PATH)
            await h.drain()
            [row] = await h.rows(
                "SELECT id, current_revision_id AS r FROM sources WHERE external_ref = %s", PATH
            )
            # One output (e.g. merged windows) names "Proxmox" as a tool and as a project.
            output = reply(
                [
                    ent("Proxmox", "tool"),
                    ent("Proxmox", "project"),
                    ent("ZFS", "tool"),
                    ent("NAS", "device"),
                ],
                [
                    rel("Proxmox", "uses", "ZFS"),  # the subject of uses is a project
                    rel("ZFS", "part_of", "Proxmox"),  # a parent shares the child's type
                    rel("Proxmox", "mentions", "NAS"),  # no type fits: skipped
                    rel("ZFS", "runs_on", "NAS"),  # unambiguous names
                ],
            )
            ctx = GraphContext(h.pool, h.ctx.settings, None, None, CommitCheckingQueue(h.pool))
            async with h.pool.connection() as conn:
                await resolve(conn, ctx, source_id=row["id"], revision_id=row["r"], output=output)
            types = {
                r["id"]: r["t"] for r in await h.rows("SELECT id, type::text AS t FROM entities")
            }
            got = {
                (r["src"], types[r["src_id"]], r["relation"], r["dst"], types[r["dst_entity_id"]])
                for r in await edges(h)
                if r["src_type"] == "entity"
            }
            assert got == {
                ("Proxmox", "project", "uses", "ZFS", "tool"),
                ("ZFS", "tool", "part_of", "Proxmox", "tool"),
                ("ZFS", "tool", "runs_on", "NAS", "device"),
            }

    run_async(go())

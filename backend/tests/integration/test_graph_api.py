from collections.abc import Callable, Iterator
from contextlib import ExitStack
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.errors import DeadlockDetected

from ai_second_brain.config import Settings
from ai_second_brain.graph import decide
from ai_second_brain.graph.prompt import EXTRACTOR_VERSION
from ai_second_brain.graph.queries import queue_extraction
from ai_second_brain.interfaces.api.app import create_app
from ai_second_brain.vault.reconcile import reconcile

from ..conftest import SAME_ORIGIN, TEST_PASSWORD, make_client, run_async
from ..fakes.ollama import FakeOllama
from ..ingest_harness import ingest_harness
from ..vaults import VaultBuilder

pytestmark = pytest.mark.integration

EVIL = {"Origin": "http://evil.example"}
NOTES = {
    "Projects/NAS.md": "# NAS\n## Dyski\nCztery dyski i Proxmox.",
    "Journal/day.md": "# Day\n## Rano\nNAS restart, Docker update.",
    "Notes/Old.md": "# Old\n## Archiwum\nThe old NAS.",
}
REPLIES: dict[str, list[Any]] = {
    "Note path: Projects/NAS.md": [
        {
            "summary": "Building the home NAS.",
            "entities": [
                {"name": "NAS", "type": "device", "aliases": [], "confidence": 0.95},
                {"name": "Proxmox", "type": "tool", "aliases": ["PVE"], "confidence": 0.9},
            ],
            "relations": [
                {"subject": "NOTE", "relation": "about", "object": "NAS", "chunk": "c1",
                 "confidence": 0.9},
                {"subject": "Proxmox", "relation": "runs_on", "object": "NAS", "chunk": "c1",
                 "confidence": 0.8},
            ],
        }
    ],
    "Note path: Journal/day.md": [
        {
            "summary": "A morning restart.",
            "entities": [
                {"name": "NAS", "type": "device", "aliases": [], "confidence": 0.9},
                {"name": "Proxmox", "type": "tool", "aliases": ["PVE"], "confidence": 0.4},
                {"name": "NAS box", "type": "device", "aliases": [], "confidence": 0.6},
                {"name": "Docker", "type": "tool", "aliases": [], "confidence": 0.7},
            ],
            "relations": [
                {"subject": "NOTE", "relation": "mentions", "object": "NAS", "chunk": "c1",
                 "confidence": 0.9},
                {"subject": "Docker", "relation": "runs_on", "object": "NAS", "chunk": "c1",
                 "confidence": 0.7},
            ],
        }
    ],
    "Note path: Notes/Old.md": [
        {
            "summary": "The old NAS.",
            "entities": [{"name": "NAS", "type": "device", "aliases": [], "confidence": 0.9}],
            "relations": [],
        }
    ],
}  # fmt: skip


@pytest.fixture
def db(db_url: str) -> Iterator[None]:
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(
            "TRUNCATE auth_sessions, sources, ingest_runs, procrastinate_jobs,"
            " entities, edges CASCADE"
        )
    yield


@pytest.fixture
def make_api(
    make_settings: Callable[..., Settings], db_url: str, db: None
) -> Iterator[Callable[..., TestClient]]:
    with ExitStack() as stack:

        def _make(*, login: bool = True, **settings: Any) -> TestClient:
            client = stack.enter_context(
                make_client(create_app(make_settings(DATABASE_URL=db_url, **settings)))
            )
            if login:
                assert (
                    client.post(
                        "/api/auth/login", json={"password": TEST_PASSWORD}, headers=SAME_ORIGIN
                    ).status_code
                    == 204
                )
            return client

        yield _make


def seed(db_url: str, root: Path, fake: FakeOllama, *, extract: bool = True) -> None:
    """Index the vault; with ``extract``, run extraction (and entity embedding) to the end."""
    fake.behaviour.chat_json_by_title = {k: list(v) for k, v in REPLIES.items()}

    async def scenario() -> None:
        async with ingest_harness(db_url, root, fake.url, extract_url=fake.url) as h:
            await reconcile(h.ctx, trigger="startup")
            await h.drain()
            if extract:
                async with h.pool.connection() as conn:
                    await queue_extraction(conn, h.ctx.queue, EXTRACTOR_VERSION, "new")
                await h.drain()  # extraction, then the embed_entity jobs it queued
                await h.drain()

    run_async(scenario())


def sql(db_url: str, query: Any, *params: Any) -> list[tuple[Any, ...]]:
    with psycopg.connect(db_url, autocommit=True) as conn:
        cur = conn.execute(query, params)
        return cur.fetchall() if cur.description is not None else []


def vault(tmp_path: Path) -> Path:
    root = tmp_path / "Brain"
    builder = VaultBuilder(root)
    for rel, text in NOTES.items():
        builder.write(rel, text)
    return root


@pytest.fixture
def graph_api(
    make_api: Callable[..., TestClient],
    db_url: str,
    tmp_path: Path,
    make_fake_ollama: Callable[[], FakeOllama],
) -> tuple[TestClient, dict[str, str]]:
    """An API over the extracted vault, plus entity ids by name."""
    fake = make_fake_ollama()
    root = vault(tmp_path)
    seed(db_url, root, fake)
    client = make_api(vault_path=str(root), embed_url_override=fake.url)
    ids = {name: str(i) for i, name in sql(db_url, "SELECT id, name FROM entities")}
    assert set(ids) == {"NAS", "Proxmox", "NAS box", "Docker"}
    return client, ids


def decide_entity(client: TestClient, entity_id: str, **body: Any) -> Any:
    return client.post(f"/api/entities/{entity_id}/decide", json=body, headers=SAME_ORIGIN)


def endpoints(url: str) -> list[dict[str, str]]:
    return [{"label": "t", "url": url, "model": "fake"}]


def test_status_and_extract(
    make_api: Callable[..., TestClient],
    db_url: str,
    tmp_path: Path,
    make_fake_ollama: Callable[[], FakeOllama],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = make_fake_ollama()
    root = vault(tmp_path)
    seed(db_url, root, fake, extract=False)
    client = make_api(vault_path=str(root), ollama_endpoints=endpoints(fake.url))
    status = client.get("/api/graph/status").json()
    assert status["model"] == "fake" and status["available"] is True
    assert status["extractor_version"] == EXTRACTOR_VERSION
    assert status["revisions"] == {"total": 3, "extracted": 0, "failed": 0, "pending": 3}
    assert status["entities"]["device"] == {"proposed": 0, "accepted": 0, "rejected": 0}
    assert status["queued"] == 0

    assert client.post("/api/graph/extract", json={"scope": "new"}, headers=EVIL).status_code == 403
    resp = client.post("/api/graph/extract", json={"scope": "new"}, headers=SAME_ORIGIN)
    assert resp.status_code == 202 and resp.json() == {"queued": 3}
    assert client.get("/api/graph/status").json()["queued"] == 3
    again = client.post("/api/graph/extract", json={"scope": "new"}, headers=SAME_ORIGIN)
    assert again.json() == {"queued": 0}  # the queueing locks hold
    failed = client.post("/api/graph/extract", json={"scope": "failed"}, headers=SAME_ORIGIN)
    assert failed.json() == {"queued": 0}
    bad = client.post("/api/graph/extract", json={"scope": "all"}, headers=SAME_ORIGIN)
    assert bad.status_code == 422

    async def no_queue() -> None:
        return None

    monkeypatch.setattr(cast(Any, client.app).state.ingest, "get_queue", no_queue)
    down = client.post("/api/graph/extract", json={"scope": "new"}, headers=SAME_ORIGIN)
    assert down.status_code == 503 and down.json() == {"detail": "database_unavailable"}

    off = make_api(vault_path=str(root))  # no endpoint, no SB_EXTRACT_MODEL
    assert off.get("/api/graph/status").json()["available"] is False
    resp = off.post("/api/graph/extract", json={"scope": "new"}, headers=SAME_ORIGIN)
    assert resp.status_code == 409 and resp.json() == {"detail": "extraction_unavailable"}

    anon = make_api(login=False)
    assert anon.get("/api/graph/status").status_code == 401


def test_status_counts_after_extraction(graph_api: tuple[TestClient, dict[str, str]]) -> None:
    client, ids = graph_api
    status = client.get("/api/graph/status").json()
    assert status["revisions"] == {"total": 3, "extracted": 3, "failed": 0, "pending": 0}
    assert status["entities"]["device"] == {"proposed": 2, "accepted": 0, "rejected": 0}
    assert status["entities"]["tool"] == {"proposed": 2, "accepted": 0, "rejected": 0}
    assert decide_entity(client, ids["Docker"], action="reject").status_code == 200
    assert client.get("/api/graph/status").json()["entities"]["tool"] == {
        "proposed": 1,
        "accepted": 0,
        "rejected": 1,
    }


def test_review_entities(graph_api: tuple[TestClient, dict[str, str]], db_url: str) -> None:
    client, ids = graph_api
    body = client.get("/api/review/entities").json()
    assert body["next_cursor"] is None
    items = {item["name"]: item for item in body["items"]}
    assert set(items) == {"NAS", "Proxmox", "NAS box", "Docker"}
    nas = items["NAS"]
    assert nas["type"] == "device" and nas["mention_count"] == 3 and nas["suggestion"] is None
    assert len(nas["samples"]) == 3
    sample = next(s for s in nas["samples"] if s["path"] == "Projects/NAS.md")
    assert sample == {
        "path": "Projects/NAS.md",
        "title": "NAS",
        "summary": "Building the home NAS.",
        "obsidian_url": "obsidian://open?vault=Brain&file=Projects%2FNAS.md",
    }
    assert items["Proxmox"]["aliases"] == ["PVE"] and items["Proxmox"]["mention_count"] == 2
    tools = client.get("/api/review/entities", params={"type": "tool"}).json()["items"]
    assert {i["name"] for i in tools} == {"Proxmox", "Docker"}

    # A near-identical name embedding of an accepted entity of the same type is a suggestion.
    assert decide_entity(client, ids["NAS"], action="accept").status_code == 200
    sql(
        db_url,
        "UPDATE entity_embeddings SET embedding ="
        " (SELECT embedding FROM entity_embeddings WHERE entity_id = %s) WHERE entity_id = %s",
        ids["NAS"],
        ids["NAS box"],
    )
    items = {i["name"]: i for i in client.get("/api/review/entities").json()["items"]}
    assert "NAS" not in items
    suggestion = items["NAS box"]["suggestion"]
    assert suggestion["id"] == ids["NAS"] and suggestion["name"] == "NAS"
    assert suggestion["similarity"] == pytest.approx(1.0, abs=1e-3)
    assert items["Docker"]["suggestion"] is None  # Proxmox (same type) isn't accepted
    sql(db_url, "DELETE FROM entity_embeddings WHERE entity_id = %s", ids["NAS box"])
    items = {i["name"]: i for i in client.get("/api/review/entities").json()["items"]}
    assert items["NAS box"]["suggestion"] is None  # no embedding yet, no suggestion

    bad = client.get("/api/review/entities", params={"cursor": "!!"})
    assert bad.status_code == 422 and bad.json() == {"detail": "invalid_cursor"}
    assert client.get("/api/review/entities", params={"type": "bogus"}).status_code == 422


def test_decide_entity(
    graph_api: tuple[TestClient, dict[str, str]],
    db_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, ids = graph_api
    resp = decide_entity(client, ids["NAS"], action="accept")
    assert resp.status_code == 200
    entity = resp.json()["entity"]
    assert entity["id"] == ids["NAS"] and entity["status"] == "accepted"
    assert len(entity["notes"]) == 3

    taken = decide_entity(client, ids["NAS box"], action="rename", name=" nas ")
    assert taken.status_code == 409 and taken.json() == {"detail": "name_taken"}
    assert (
        decide_entity(client, ids["NAS box"], action="parent", parent_id=ids["NAS"]).json()[
            "entity"
        ]["parent"]
        is None
    )  # NAS box itself isn't accepted yet, so the link isn't shown
    cycle = decide_entity(client, ids["NAS"], action="parent", parent_id=ids["NAS box"])
    assert cycle.status_code == 422 and cycle.json() == {"detail": "parent_cycle"}
    mismatch = decide_entity(client, ids["Proxmox"], action="merge", into_id=ids["NAS"])
    assert mismatch.status_code == 422 and mismatch.json() == {"detail": "type_mismatch"}
    for body in ({"action": "explode"}, {"action": "rename"}, {"action": "merge"}):
        resp = decide_entity(client, ids["NAS"], **body)
        assert resp.status_code == 422 and resp.json() == {"detail": "invalid_action"}
    for bad_name in ("a\u0000b", "a\u0007b"):  # NUL and other control characters
        resp = decide_entity(client, ids["NAS box"], action="rename", name=bad_name)
        assert resp.status_code == 422 and resp.json() == {"detail": "invalid_action"}
    retype = decide_entity(client, ids["NAS"], action="retype", type="bogus")
    assert retype.json() == {"detail": "invalid_action"}
    missing = decide_entity(client, str(uuid4()), action="accept")
    assert missing.status_code == 404 and missing.json() == {"detail": "not_found"}
    evil = client.post(
        f"/api/entities/{ids['NAS']}/decide", json={"action": "accept"}, headers=EVIL
    )
    assert evil.status_code == 403

    renamed = decide_entity(client, ids["NAS box"], action="rename", name="Storage box")
    assert renamed.json()["entity"]["name"] == "Storage box"
    assert renamed.json()["entity"]["aliases"] == ["NAS box"]

    # A merge into an entity with no embedding queues one for it, after the commit.
    sql(db_url, "DELETE FROM entity_embeddings WHERE entity_id = %s", ids["Proxmox"])
    sql(db_url, "DELETE FROM procrastinate_jobs")
    merged = decide_entity(client, ids["Docker"], action="merge", into_id=ids["Proxmox"])
    assert merged.status_code == 200
    assert merged.json()["entity"]["id"] == ids["Proxmox"]
    assert "Docker" in merged.json()["entity"]["aliases"]
    jobs = sql(
        db_url,
        "SELECT args->>'entity_id' FROM procrastinate_jobs"
        " WHERE task_name = 'ingest:graph_embed_entity'",
    )
    assert jobs == [(ids["Proxmox"],)]
    assert client.get(f"/api/entities/{ids['Docker']}").status_code == 404

    # A deadlock loser is retried once, then the answer is 409 busy.
    calls: list[UUID] = []

    async def deadlock(conn: Any, entity_id: UUID) -> None:
        calls.append(entity_id)
        raise DeadlockDetected("deadlock detected")

    monkeypatch.setattr(decide, "accept_entity", deadlock)
    busy = decide_entity(client, ids["Proxmox"], action="accept")
    assert busy.status_code == 409 and busy.json() == {"detail": "busy"}
    assert len(calls) == 2


def test_review_and_decide_links(graph_api: tuple[TestClient, dict[str, str]], db_url: str) -> None:
    client, ids = graph_api
    for name in ("NAS", "Proxmox"):
        assert decide_entity(client, ids[name], action="accept").status_code == 200
    body = client.get("/api/review/links").json()
    assert body["next_cursor"] is None
    assert len(body["items"]) == 3
    relations = [i for i in body["items"] if i["kind"] == "relation"]
    [mention] = [i for i in body["items"] if i["kind"] == "mention"]
    by_subject = {i["subject"]["name"]: i for i in relations}
    assert set(by_subject) == {"Proxmox", "Docker"}  # Docker is proposed, not rejected
    proxmox = by_subject["Proxmox"]
    assert proxmox["note"] is None and proxmox["subject"]["id"] == ids["Proxmox"]
    assert proxmox["object"] == {"id": ids["NAS"], "name": "NAS", "type": "device"}
    assert proxmox["confidence"] == pytest.approx(0.8)
    assert proxmox["evidence"] == {
        "path": "Projects/NAS.md",
        "heading": "Dyski",
        "obsidian_url": "obsidian://open?vault=Brain&file=Projects%2FNAS.md",
    }
    # Journal mentions Proxmox at 0.4: below the accept bar, so still proposed.
    assert mention["relation"] == "mentions" and mention["object"]["name"] == "Proxmox"
    assert mention["subject"] is None
    assert mention["note"]["path"] == "Journal/day.md" and mention["note"]["title"] == "Day"
    assert mention["evidence"]["path"] == "Journal/day.md"
    assert mention["evidence"]["heading"] is None  # no chunk named Proxmox in that note

    # An edge whose entity at either end is rejected never shows, even if still proposed.
    sql(db_url, "UPDATE entities SET status = 'rejected' WHERE id = %s", ids["Docker"])
    items = client.get("/api/review/links").json()["items"]
    assert {i["id"] for i in items} == {proxmox["id"], mention["id"]}

    # Evidence from a tombstoned note is null (the relation itself stays reviewable).
    sql(db_url, "UPDATE sources SET deleted_at = now() WHERE external_ref = 'Projects/NAS.md'")
    items = {i["id"]: i for i in client.get("/api/review/links").json()["items"]}
    assert items[proxmox["id"]]["evidence"] is None
    sql(db_url, "UPDATE sources SET deleted_at = NULL WHERE external_ref = 'Projects/NAS.md'")

    too_many = {"items": [{"id": str(uuid4()), "decision": "accept"}] * 101}
    assert client.post("/api/review/links", json=too_many, headers=SAME_ORIGIN).status_code == 422
    wrong = {"items": [{"id": proxmox["id"], "decision": "maybe"}]}
    assert client.post("/api/review/links", json=wrong, headers=SAME_ORIGIN).status_code == 422
    batch = {
        "items": [
            {"id": proxmox["id"], "decision": "accept"},
            {"id": mention["id"], "decision": "reject"},
            {"id": str(uuid4()), "decision": "accept"},
        ]
    }
    assert client.post("/api/review/links", json=batch, headers=EVIL).status_code == 403
    resp = client.post("/api/review/links", json=batch, headers=SAME_ORIGIN)
    assert resp.status_code == 200 and resp.json() == {"updated": 2}
    assert client.get("/api/review/links").json()["items"] == []

    nas = client.get(f"/api/entities/{ids['NAS']}").json()
    assert nas["related"] == [
        {
            "relation": "runs_on",
            "direction": "in",
            "entity": {"id": ids["Proxmox"], "name": "Proxmox", "type": "tool"},
        }
    ]
    pve = client.get(f"/api/entities/{ids['Proxmox']}").json()
    assert pve["related"] == [
        {
            "relation": "runs_on",
            "direction": "out",
            "entity": {"id": ids["NAS"], "name": "NAS", "type": "device"},
        }
    ]
    assert [n["path"] for n in pve["notes"]] == ["Projects/NAS.md"]  # journal edge rejected

    bad = client.get("/api/review/links", params={"cursor": "e30"})  # "{}"
    assert bad.status_code == 422 and bad.json() == {"detail": "invalid_cursor"}


def test_list_entities_and_detail(
    graph_api: tuple[TestClient, dict[str, str]], db_url: str
) -> None:
    client, ids = graph_api
    for name in ("NAS", "Proxmox", "NAS box"):
        assert decide_entity(client, ids[name], action="accept").status_code == 200
    assert decide_entity(client, ids["NAS box"], action="parent", parent_id=ids["NAS"]).json()[
        "entity"
    ]["parent"] == {"id": ids["NAS"], "name": "NAS", "type": "device"}

    body = client.get("/api/entities", params={"type": "device", "q": "na"}).json()
    assert body == {
        "items": [
            {"id": ids["NAS"], "name": "NAS", "type": "device", "note_count": 3},
            {"id": ids["NAS box"], "name": "NAS box", "type": "device", "note_count": 1},
        ],
        "next_cursor": None,
    }
    everything = client.get("/api/entities").json()["items"]
    assert [i["name"] for i in everything] == ["NAS", "NAS box", "Proxmox"]  # Docker: proposed
    assert client.get("/api/entities", params={"q": "pve"}).json()["items"][0]["name"] == "Proxmox"
    assert client.get("/api/entities", params={"q": "n%"}).json()["items"] == []
    nul = client.get("/api/entities", params={"q": "a\x00b"})
    assert nul.status_code == 422 and nul.json() == {"detail": "invalid_query"}
    assert client.get("/api/entities", params={"q": "x" * 201}).status_code == 422
    bad = client.get("/api/entities", params={"cursor": "bm90LWpzb24"})
    assert bad.status_code == 422 and bad.json() == {"detail": "invalid_cursor"}

    nas = client.get(f"/api/entities/{ids['NAS']}").json()
    assert nas["name"] == "NAS" and nas["type"] == "device" and nas["status"] == "accepted"
    assert nas["parent"] is None
    assert nas["children"] == [{"id": ids["NAS box"], "name": "NAS box", "type": "device"}]
    notes = {n["path"]: n for n in nas["notes"]}
    assert set(notes) == {"Projects/NAS.md", "Journal/day.md", "Notes/Old.md"}
    main = notes["Projects/NAS.md"]
    assert main == {
        "source_id": main["source_id"],
        "path": "Projects/NAS.md",
        "title": "NAS",
        "summary": "Building the home NAS.",
        "heading": "Dyski",
        "relation": "about",
        "obsidian_url": "obsidian://open?vault=Brain&file=Projects%2FNAS.md",
    }
    assert notes["Journal/day.md"]["relation"] == "mentions"
    assert notes["Journal/day.md"]["heading"] == "Rano"
    assert notes["Notes/Old.md"]["heading"] is None  # no evidence chunk named

    # A tombstoned note drops out of the notes and the counts.
    sql(db_url, "UPDATE sources SET deleted_at = now() WHERE external_ref = 'Notes/Old.md'")
    nas = client.get(f"/api/entities/{ids['NAS']}").json()
    assert {n["path"] for n in nas["notes"]} == {"Projects/NAS.md", "Journal/day.md"}
    listed = client.get("/api/entities", params={"type": "device"}).json()["items"]
    assert listed[0] == {"id": ids["NAS"], "name": "NAS", "type": "device", "note_count": 2}

    # A proposed entity has a page but shows no notes or relations.
    docker = client.get(f"/api/entities/{ids['Docker']}").json()
    assert docker["status"] == "proposed" and docker["notes"] == [] and docker["related"] == []
    missing = client.get(f"/api/entities/{uuid4()}")
    assert missing.status_code == 404 and missing.json() == {"detail": "not_found"}
    assert client.get("/api/entities/not-a-uuid").status_code == 422


def test_pages_walk_with_cursors(make_api: Callable[..., TestClient], db_url: str) -> None:
    sql(
        db_url,
        "INSERT INTO entities (type, name, norm_name, status, created_at)"
        " SELECT 'topic', 'Topic ' || i, 'topic ' || i,"
        " CASE WHEN i <= 25 THEN 'proposed' ELSE 'accepted' END::graph_status,"
        " now() - make_interval(secs => 100 - i)"
        " FROM generate_series(1, 85) AS i",
    )
    client = make_api()

    def walk(url: str) -> list[list[str]]:
        pages, cursor = [], None
        while True:
            params = {"cursor": cursor} if cursor else {}
            body = client.get(url, params=params).json()
            pages.append([i["name"] for i in body["items"]])
            cursor = body["next_cursor"]
            if cursor is None:
                return pages

    review = walk("/api/review/entities")
    assert [len(p) for p in review] == [20, 5]
    assert sum(review, []) == [f"Topic {i}" for i in range(1, 26)]  # oldest first
    listed = walk("/api/entities")
    assert [len(p) for p in listed] == [50, 10]
    flat = sum(listed, [])
    assert flat == sorted(flat) and len(set(flat)) == 60  # all at note count 0: by name

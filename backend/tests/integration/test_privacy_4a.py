import logging
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from ai_second_brain.config import Settings
from ai_second_brain.graph.prompt import EXTRACTOR_VERSION
from ai_second_brain.graph.queries import queue_extraction
from ai_second_brain.interfaces.api.app import create_app
from ai_second_brain.vault.reconcile import reconcile

from ..conftest import SAME_ORIGIN, TEST_PASSWORD, make_client, run_async
from ..fakes.ollama import FakeOllama
from ..ingest_harness import ingest_harness
from ..vaults import VaultBuilder

pytestmark = pytest.mark.integration

PATH = "Hidden/SecretPathQX.md"
REPLY: dict[str, Any] = {
    "summary": "SecretSummaryQX",
    "entities": [
        {"name": "SecretPersonQX", "type": "person", "aliases": [], "confidence": 0.9},
        {"name": "SecretToolQX", "type": "tool", "aliases": ["SecretAliasQX"], "confidence": 0.9},
    ],
    "relations": [
        {"subject": "NOTE", "relation": "about", "object": "SecretToolQX", "chunk": "c1",
         "confidence": 0.9},
        {"subject": "SecretPersonQX", "relation": "works_with", "object": "SecretToolQX",
         "chunk": "c1", "confidence": 0.8},
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


def test_extraction_decisions_and_entity_pages_log_nothing_private(
    make_api: Callable[..., TestClient],
    db_url: str,
    tmp_path: Path,
    make_fake_ollama: Callable[[], FakeOllama],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    for name in ("ai_second_brain", "procrastinate"):
        caplog.set_level(logging.DEBUG, logger=name)
    fake = make_fake_ollama()
    fake.behaviour.chat_json_by_title = {"SecretPathQX": [REPLY]}
    root = tmp_path / "Brain"
    VaultBuilder(root).write(
        PATH, "# SecretTitleQX\n## Part\nSecretBodyQX with SecretPersonQX and SecretToolQX.\n"
    )

    async def extract() -> None:
        async with ingest_harness(db_url, root, fake.url, extract_url=fake.url) as h:
            await reconcile(h.ctx, trigger="startup")
            await h.drain()
            async with h.pool.connection() as conn:
                await queue_extraction(conn, h.ctx.queue, EXTRACTOR_VERSION, "new")
            await h.drain()  # extraction, then the entity embeddings it queued
            await h.drain()

    run_async(extract())
    client = make_api(vault_path=str(root), embed_url_override=fake.url)

    review = client.get("/api/review/entities").json()["items"]
    ids = {item["name"]: item["id"] for item in review}
    assert set(ids) == {"SecretPersonQX", "SecretToolQX"}
    assert review[0]["samples"][0]["summary"] == "SecretSummaryQX"
    for entity_id in ids.values():
        accepted = client.post(
            f"/api/entities/{entity_id}/decide", json={"action": "accept"}, headers=SAME_ORIGIN
        )
        assert accepted.status_code == 200
    renamed = client.post(
        f"/api/entities/{ids['SecretToolQX']}/decide",
        json={"action": "rename", "name": "SecretRenamedQX"},
        headers=SAME_ORIGIN,
    )
    assert renamed.status_code == 200
    links = client.get("/api/review/links").json()["items"]
    assert [link["subject"]["name"] for link in links] == ["SecretPersonQX"]
    decided = client.post(
        "/api/review/links",
        json={"items": [{"id": links[0]["id"], "decision": "accept"}]},
        headers=SAME_ORIGIN,
    )
    assert decided.json() == {"updated": 1}
    page = client.get(f"/api/entities/{ids['SecretToolQX']}").json()
    assert page["notes"][0]["summary"] == "SecretSummaryQX"
    assert page["related"][0]["entity"]["name"] == "SecretPersonQX"
    listed = client.get("/api/entities", params={"q": "SecretQueryQX"})
    assert listed.json()["items"] == []
    assert client.get("/api/graph/status").status_code == 200

    # Format every record, tracebacks included. Only the test client's own request lines
    # (httpx logging "http://testserver/...?q=...") are excluded.
    def is_test_client(r: logging.LogRecord) -> bool:
        return r.name.split(".")[0] in {"httpx", "httpcore"} or (
            r.name.startswith("httpx") and "//testserver/" in r.getMessage()
        )

    app_log = "\n".join(caplog.handler.format(r) for r in caplog.records if not is_test_client(r))
    assert "extract revision=" in app_log and "decide action=accept" in app_log  # it did log
    secrets = [
        "SecretPersonQX",
        "SecretToolQX",
        "SecretAliasQX",
        "SecretRenamedQX",
        "SecretSummaryQX",
        "SecretTitleQX",
        "SecretBodyQX",
        "SecretPathQX",
        "SecretQueryQX",
    ]
    assert [s for s in secrets if s in app_log] == []

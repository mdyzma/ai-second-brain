import logging
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from ai_second_brain.config import Settings
from ai_second_brain.interfaces.api.app import create_app
from ai_second_brain.search.embedding import QueryEmbedder
from ai_second_brain.search.retriever import HybridRetriever
from ai_second_brain.vault.reconcile import reconcile

from ..conftest import SAME_ORIGIN, TEST_PASSWORD, make_client, run_async
from ..fakes.ollama import FakeOllama
from ..ingest_harness import ingest_harness
from ..vaults import VaultBuilder

pytestmark = pytest.mark.integration


@pytest.fixture
def db(db_url: str) -> Iterator[None]:
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("TRUNCATE auth_sessions, sources, ingest_runs, procrastinate_jobs CASCADE")
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


def seed(db_url: str, root: Path, embed_url: str, drain: bool = True) -> None:
    async def scenario() -> None:
        async with ingest_harness(db_url, root, embed_url) as h:
            await reconcile(h.ctx, trigger="startup")
            if drain:
                await h.drain()

    run_async(scenario())


def test_search_retrieval_and_capture_log_nothing_private(
    make_api: Callable[..., TestClient],
    db_url: str,
    tmp_path: Path,
    make_fake_ollama: Callable[[], FakeOllama],
    make_settings: Callable[..., Settings],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    for name in ("ai_second_brain", "procrastinate"):
        caplog.set_level(logging.DEBUG, logger=name)
    fake = make_fake_ollama()
    root = tmp_path / "Brain"
    VaultBuilder(root).write("Hidden/SecretPathQX.md", "# SecretTitleQX\nSecretBodyQX here\n")
    seed(db_url, root, fake.url)
    client = make_api(vault_path=str(root), embed_url_override=fake.url)

    assert client.get("/api/search", params={"q": "SecretQueryQX"}).status_code == 200
    hits = client.get("/api/search", params={"q": "SecretBodyQX"}).json()["results"]
    assert [h["path"] for h in hits] == ["Hidden/SecretPathQX.md"]

    async def retrieve() -> None:
        settings = make_settings(DATABASE_URL=db_url, vault_path=str(root))
        async with ingest_harness(db_url, root, fake.url) as h:
            retriever = HybridRetriever(h.pool, QueryEmbedder(None), settings)
            await retriever.retrieve("SecretBodyQX question", 8)

    run_async(retrieve())

    created = client.post(
        "/api/capture",
        json={"text": "SecretCaptureQX\nSecretCaptureBodyQX"},
        headers=SAME_ORIGIN,
    )
    assert created.status_code == 201

    # Format every record, tracebacks included, so an exception naming a path fails the test.
    # Only the test client's own request lines (httpx logging "http://testserver/...?q=...")
    # are excluded; the app's outbound httpx2/httpcore2 records stay in.
    def is_test_client(r: logging.LogRecord) -> bool:
        return r.name.split(".")[0] in {"httpx", "httpcore"} or (
            r.name.startswith("httpx") and "//testserver/" in r.getMessage()
        )

    app_log = "\n".join(caplog.handler.format(r) for r in caplog.records if not is_test_client(r))
    assert "search q_len=" in app_log and "capture outcome=ok" in app_log  # the scenario did log
    secrets = [
        "SecretTitleQX",
        "SecretBodyQX",
        "SecretPathQX",
        "SecretQueryQX",
        "SecretCaptureQX",
        "SecretCaptureBodyQX",
    ]
    assert [s for s in secrets if s in app_log] == []

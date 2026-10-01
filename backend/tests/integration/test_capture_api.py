from collections.abc import Callable, Iterator
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from ai_second_brain.config import Settings
from ai_second_brain.interfaces.api.app import create_app
from ai_second_brain.vault.reconcile import reconcile

from ..conftest import SAME_ORIGIN, TEST_PASSWORD, make_client, run_async
from ..fakes.ollama import FakeOllama
from ..ingest_harness import ingest_harness

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


def test_capture_writes_and_worker_indexes(
    make_api: Callable[..., TestClient],
    db_url: str,
    tmp_path: Path,
    make_fake_ollama: Callable[[], FakeOllama],
) -> None:
    fake = make_fake_ollama()
    client = make_api(vault_path=str(tmp_path / "Brain"), embed_url_override=fake.url)
    response = client.post(
        "/api/capture", json={"text": "Zebra thought\nstripes"}, headers=SAME_ORIGIN
    )
    assert response.status_code == 201
    body = response.json()
    assert body["path"].startswith("Inbox/") and body["title"] == "Zebra thought"
    assert body["obsidian_url"].startswith("obsidian://open?vault=Brain&file=Inbox%2F")
    seed(db_url, tmp_path / "Brain", fake.url)
    found = client.get("/api/search", params={"q": "stripes"}).json()["results"]
    assert [r["path"] for r in found] == [body["path"]]


def test_capture_errors(make_api: Callable[..., TestClient], db_url: str, tmp_path: Path) -> None:
    disabled = make_api().post("/api/capture", json={"text": "x"}, headers=SAME_ORIGIN)
    assert disabled.json() == {"detail": "vault_disabled"}
    client = make_api(vault_path=str(tmp_path))
    assert client.post("/api/capture", json={"text": "  "}, headers=SAME_ORIGIN).status_code == 422
    bad = client.post("/api/capture", json={"text": "a\x00"}, headers=SAME_ORIGIN)
    assert bad.json() == {"detail": "invalid_text"}
    long = client.post("/api/capture", json={"text": "x" * 20001}, headers=SAME_ORIGIN)
    assert long.status_code == 422
    evil = client.post(
        "/api/capture", json={"text": "x"}, headers={"Origin": "https://evil.example"}
    )
    assert evil.status_code == 403


def test_capture_unwritable(
    make_api: Callable[..., TestClient],
    db_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_second_brain.vault import capture as capture_module

    def boom(*args: object) -> str:
        raise PermissionError("denied /secret/path")

    monkeypatch.setattr(capture_module, "write_capture", boom)
    client = make_api(vault_path=str(tmp_path))
    response = client.post("/api/capture", json={"text": "x"}, headers=SAME_ORIGIN)
    assert response.status_code == 503
    assert response.json() == {"detail": "vault_unwritable"}

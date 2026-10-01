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


def test_search_returns_hits_with_links_and_vector_status(
    make_api: Callable[..., TestClient],
    db_url: str,
    tmp_path: Path,
    make_fake_ollama: Callable[[], FakeOllama],
) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path / "Brain")
    vault.write("Projects/NAS.md", "---\ntags: [homelab]\n---\n# NAS\n## Dyski\nCztery dyski.")
    seed(db_url, tmp_path / "Brain", fake.url)
    client = make_api(vault_path=str(tmp_path / "Brain"), embed_url_override=fake.url)
    body = client.get("/api/search", params={"q": "dyski"}).json()
    assert body["vector"] == "ok"
    [hit] = body["results"]
    assert hit["path"] == "Projects/NAS.md" and hit["title"] == "NAS"
    assert hit["heading_path"] == ["Dyski"]
    assert "<mark>dyski</mark>" in hit["snippet"].lower()
    assert "text" in hit["matched"]
    assert hit["obsidian_url"] == "obsidian://open?vault=Brain&file=Projects%2FNAS.md"


def test_search_falls_back_to_text_when_ollama_down(
    make_api: Callable[..., TestClient],
    db_url: str,
    tmp_path: Path,
    make_fake_ollama: Callable[[], FakeOllama],
) -> None:
    fake = make_fake_ollama()
    VaultBuilder(tmp_path).write("a.md", "# A\nzebra")
    seed(db_url, tmp_path, fake.url)
    fake.behaviour.embed_status = 500
    client = make_api(vault_path=str(tmp_path), embed_url_override=fake.url)
    body = client.get("/api/search", params={"q": "zebra"}).json()
    assert body["vector"] == "unavailable" and [r["path"] for r in body["results"]] == ["a.md"]
    calls = len(fake.embed_requests())
    client.get("/api/search", params={"q": "zebra"})
    assert len(fake.embed_requests()) == calls  # breaker: no second attempt within 30 s


def test_search_filters_and_validation(
    make_api: Callable[..., TestClient],
    db_url: str,
    tmp_path: Path,
    make_fake_ollama: Callable[[], FakeOllama],
) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("Projects/a.md", "---\ntags: [homelab]\n---\n# A\nzebra")
    vault.write("Journal/b.md", "# B\nzebra")
    seed(db_url, tmp_path, fake.url)
    client = make_api(vault_path=str(tmp_path), embed_url_override=fake.url)

    def paths(**p: Any) -> list[str]:
        resp = client.get("/api/search", params={"q": "zebra", **p}).json()
        return [r["path"] for r in resp["results"]]

    assert paths(folder="Projects") == ["Projects/a.md"]
    assert paths(tag=["#HomeLab"]) == ["Projects/a.md"]
    assert client.get("/api/search", params={"q": "  "}).status_code == 422
    assert client.get("/api/search", params={"q": "a\x00b"}).json() == {"detail": "invalid_query"}
    assert client.get("/api/search", params={"q": "x" * 501}).status_code == 422
    assert client.get("/api/search", params={"q": "x", "limit": 51}).status_code == 422


def test_search_needs_vault_and_session(make_api: Callable[..., TestClient], db_url: str) -> None:
    client = make_api()
    assert client.get("/api/search", params={"q": "x"}).json() == {"detail": "vault_disabled"}
    anon = make_api(login=False)
    assert anon.get("/api/search", params={"q": "x"}).status_code == 401


def test_facets(
    make_api: Callable[..., TestClient],
    db_url: str,
    tmp_path: Path,
    make_fake_ollama: Callable[[], FakeOllama],
) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("Projects/Home/a.md", "---\ntags: [homelab, nas]\n---\nx")
    vault.write("Projects/b.md", "---\ntags: [homelab]\n---\nx")
    vault.write("root.md", "x")
    seed(db_url, tmp_path, fake.url)
    client = make_api(vault_path=str(tmp_path), embed_url_override=fake.url)
    body = client.get("/api/search/facets").json()
    assert body["folders"] == [
        {"path": "Projects", "count": 2},
        {"path": "Projects/Home", "count": 1},
    ]
    assert body["tags"] == [{"tag": "homelab", "count": 2}, {"tag": "nas", "count": 1}]

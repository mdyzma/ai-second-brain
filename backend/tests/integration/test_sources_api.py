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
EVIL = {"Origin": "https://evil.example"}


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


def test_summary_and_list(
    make_api: Callable[..., TestClient],
    db_url: str,
    tmp_path: Path,
    make_fake_ollama: Callable[[], FakeOllama],
) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("Projects/NAS.md", "# NAS\ndyski")
    vault.write("big.md", "x" * 3_000_000)
    seed(db_url, tmp_path, fake.url)
    client = make_api(vault_path=str(tmp_path), embed_url_override=fake.url)
    summary = client.get("/api/sources/summary").json()
    assert summary["vault"] == {"configured": True, "readable": True}
    assert summary["sources"] == {"active": 2, "deleted": 0}
    assert summary["revisions"]["indexed"] == 1 and summary["revisions"]["failed"] == 1
    assert summary["embedding"]["model"] == "bge-m3"
    assert summary["embedding"]["embedded"] == summary["embedding"]["total"] == 1
    assert summary["embedding"]["host_reachable"] is True
    assert summary["last_run"]["outcome"] == "ok"
    listing = client.get("/api/sources").json()
    assert [(r["path"], r["state"], r["chunks"], r["embedded"]) for r in listing["items"]] == [
        ("Projects/NAS.md", "indexed", 1, 1),
        ("big.md", "failed", 0, 0),
    ]
    assert listing["items"][1]["error"] == "too_large"
    assert (
        client.get("/api/sources", params={"state": "failed"}).json()["items"][0]["path"]
        == "big.md"
    )
    assert [r["path"] for r in client.get("/api/sources", params={"q": "nas"}).json()["items"]] == [
        "Projects/NAS.md"
    ]


def test_cursor_pagination(
    make_api: Callable[..., TestClient],
    db_url: str,
    tmp_path: Path,
    make_fake_ollama: Callable[[], FakeOllama],
) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    for i in range(55):
        vault.write(f"n{i:02d}.md", f"note {i}")
    seed(db_url, tmp_path, fake.url, drain=False)
    client = make_api(vault_path=str(tmp_path))
    first = client.get("/api/sources").json()
    assert len(first["items"]) == 50 and first["next_cursor"]
    second = client.get("/api/sources", params={"cursor": first["next_cursor"]}).json()
    assert [r["path"] for r in second["items"]] == [f"n{i}.md" for i in range(50, 55)]
    assert second["next_cursor"] is None


def test_retry_and_reconcile(
    make_api: Callable[..., TestClient],
    db_url: str,
    tmp_path: Path,
    make_fake_ollama: Callable[[], FakeOllama],
) -> None:
    fake = make_fake_ollama()
    fake.behaviour.embed_status = 404
    fake.behaviour.embed_error_text = "model not found"
    VaultBuilder(tmp_path).write("a.md", "x")
    seed(db_url, tmp_path, fake.url)
    client = make_api(vault_path=str(tmp_path), embed_url_override=fake.url)
    [row] = client.get("/api/sources").json()["items"]
    assert (
        client.get("/api/sources/summary").json()["embedding"]["last_error"]
        == "embed_model_missing"
    )
    assert client.post(f"/api/sources/{row['id']}/retry", headers=SAME_ORIGIN).status_code == 202
    assert (
        client.post(f"/api/sources/{row['id']}/retry", headers=SAME_ORIGIN).status_code == 202
    )  # still missing vectors
    missing = client.post(
        "/api/sources/00000000-0000-4000-8000-000000000000/retry", headers=SAME_ORIGIN
    )
    assert (missing.status_code, missing.json()) == (404, {"detail": "not_found"})
    queued = client.post("/api/sources/reconcile", headers=SAME_ORIGIN)
    assert queued.status_code == 202 and isinstance(queued.json()["run_id"], int)
    disabled = make_api().post("/api/sources/reconcile", headers=SAME_ORIGIN)
    assert (disabled.status_code, disabled.json()) == (409, {"detail": "vault_disabled"})


def test_nothing_to_retry(
    make_api: Callable[..., TestClient],
    db_url: str,
    tmp_path: Path,
    make_fake_ollama: Callable[[], FakeOllama],
) -> None:
    fake = make_fake_ollama()
    VaultBuilder(tmp_path).write("a.md", "x")
    seed(db_url, tmp_path, fake.url)
    client = make_api(vault_path=str(tmp_path))
    [row] = client.get("/api/sources").json()["items"]
    response = client.post(f"/api/sources/{row['id']}/retry", headers=SAME_ORIGIN)
    assert (response.status_code, response.json()) == (409, {"detail": "nothing_to_retry"})


def test_auth_and_csrf(make_api: Callable[..., TestClient]) -> None:
    client = make_api()
    assert client.post("/api/sources/reconcile", headers=EVIL).status_code == 403
    anonymous = make_api(login=False)
    for method, path in [
        ("GET", "/api/sources/summary"),
        ("GET", "/api/sources"),
        ("POST", "/api/sources/reconcile"),
    ]:
        assert anonymous.request(method, path, headers=SAME_ORIGIN).status_code == 401


class _BrokenQueue:
    async def reconcile(self, run_id: int) -> None:
        raise ConnectionError("queue down")


def test_reconcile_queue_failure_finishes_the_run(
    make_api: Callable[..., TestClient], db_url: str, tmp_path: Path
) -> None:
    client = make_api(vault_path=str(tmp_path))
    client.app.state.ingest.queue = _BrokenQueue()  # type: ignore[attr-defined]
    response = client.post("/api/sources/reconcile", headers=SAME_ORIGIN)
    assert (response.status_code, response.json()) == (503, {"detail": "database_unavailable"})
    with psycopg.connect(db_url) as conn:
        rows = conn.execute("SELECT outcome, finished_at IS NOT NULL FROM ingest_runs").fetchall()
    assert rows == [("error:queue_unavailable", True)]


def test_routes_return_503_when_the_job_app_failed_to_open(
    monkeypatch: pytest.MonkeyPatch, make_api: Callable[..., TestClient], tmp_path: Path
) -> None:
    class _Broken:
        async def open_async(self) -> None:
            raise OSError("no database")

        async def close_async(self) -> None:
            return None

    monkeypatch.setattr("ai_second_brain.interfaces.api.app.create_job_app", lambda _url: _Broken())
    client = make_api(vault_path=str(tmp_path))
    assert client.get("/api/sources/summary").status_code == 200
    for path in (
        "/api/sources/reconcile",
        "/api/sources/00000000-0000-4000-8000-000000000000/retry",
    ):
        response = client.post(path, headers=SAME_ORIGIN)
        assert (response.status_code, response.json()) == (503, {"detail": "database_unavailable"})

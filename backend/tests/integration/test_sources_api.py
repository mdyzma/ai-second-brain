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
    async def reconcile(self, run_id: int) -> bool:
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

    monkeypatch.setattr(
        "ai_second_brain.interfaces.api.app.create_job_app", lambda *_a, **_k: _Broken()
    )
    client = make_api(vault_path=str(tmp_path))
    assert client.get("/api/sources/summary").status_code == 200
    for path in (
        "/api/sources/reconcile",
        "/api/sources/00000000-0000-4000-8000-000000000000/retry",
    ):
        response = client.post(path, headers=SAME_ORIGIN)
        assert (response.status_code, response.json()) == (503, {"detail": "database_unavailable"})


@pytest.mark.parametrize("cursor", ["a", "_w", "AA"])
def test_bad_cursor_is_422(make_api: Callable[..., TestClient], cursor: str) -> None:
    response = make_api().get("/api/sources", params={"cursor": cursor})
    assert (response.status_code, response.json()) == (422, {"detail": "invalid_cursor"})


def test_search_escapes_wildcards_and_rejects_nul(
    make_api: Callable[..., TestClient],
    db_url: str,
    tmp_path: Path,
    make_fake_ollama: Callable[[], FakeOllama],
) -> None:
    vault = VaultBuilder(tmp_path)
    vault.write("a_b.md", "one")
    vault.write("axb.md", "two")
    vault.write("50%.md", "three")
    seed(db_url, tmp_path, make_fake_ollama().url, drain=False)
    client = make_api(vault_path=str(tmp_path))

    def paths(q: str) -> list[str]:
        return [r["path"] for r in client.get("/api/sources", params={"q": q}).json()["items"]]

    assert paths("_") == ["a_b.md"]
    assert paths("%") == ["50%.md"]
    assert paths("a\\") == []
    assert client.get("/api/sources", params={"q": "a\x00"}).status_code == 422


def test_retry_on_a_deleted_source_is_nothing_to_retry(
    make_api: Callable[..., TestClient],
    db_url: str,
    tmp_path: Path,
    make_fake_ollama: Callable[[], FakeOllama],
) -> None:
    VaultBuilder(tmp_path).write("big.md", "x" * 3_000_000)
    seed(db_url, tmp_path, make_fake_ollama().url)
    client = make_api(vault_path=str(tmp_path))
    [row] = client.get("/api/sources").json()["items"]
    assert row["state"] == "failed"
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("UPDATE sources SET deleted_at = now()")
    response = client.post(f"/api/sources/{row['id']}/retry", headers=SAME_ORIGIN)
    assert (response.status_code, response.json()) == (409, {"detail": "nothing_to_retry"})
    with psycopg.connect(db_url) as conn:
        assert conn.execute("SELECT state FROM source_revisions").fetchall() == [("failed",)]


def test_job_app_opens_lazily_after_the_database_recovers(
    monkeypatch: pytest.MonkeyPatch, make_api: Callable[..., TestClient], tmp_path: Path
) -> None:
    class _Flaky:
        opens = 0
        closes = 0

        async def open_async(self) -> None:
            _Flaky.opens += 1
            if _Flaky.opens == 1:
                raise OSError("no database")

        async def close_async(self) -> None:
            _Flaky.closes += 1

    monkeypatch.setattr(
        "ai_second_brain.interfaces.api.app.create_job_app", lambda *_a, **_k: _Flaky()
    )
    client = make_api(vault_path=str(tmp_path))
    assert client.app.state.ingest.queue is None  # type: ignore[attr-defined]
    missing = client.post(
        "/api/sources/00000000-0000-4000-8000-000000000000/retry", headers=SAME_ORIGIN
    )
    assert (missing.status_code, missing.json()) == (404, {"detail": "not_found"})
    assert _Flaky.opens == 2
    client.get("/api/sources/summary")
    assert _Flaky.opens == 2  # opened once more only, not per request


def test_unreachable_database_fails_the_open_quickly_and_can_retry() -> None:
    import time

    from ai_second_brain.knowledge.jobs import create_job_app

    async def scenario() -> float:
        app = create_job_app("postgres://u@127.0.0.1:1/x", open_timeout=1.0)
        start = time.monotonic()
        for _ in range(2):  # the second try proves a failed open leaves nothing half-open
            with pytest.raises(Exception):  # noqa: B017, PT011
                await app.open_async()
            await app.close_async()
        return time.monotonic() - start

    assert run_async(scenario()) < 10


def test_retry_on_a_read_error_is_nothing_to_retry(
    make_api: Callable[..., TestClient],
    db_url: str,
    tmp_path: Path,
    make_fake_ollama: Callable[[], FakeOllama],
) -> None:
    VaultBuilder(tmp_path).write("big.md", "x" * 3_000_000)
    seed(db_url, tmp_path, make_fake_ollama().url)
    client = make_api(vault_path=str(tmp_path))
    [row] = client.get("/api/sources").json()["items"]
    assert (row["state"], row["error"]) == ("failed", "too_large")
    response = client.post(f"/api/sources/{row['id']}/retry", headers=SAME_ORIGIN)
    assert (response.status_code, response.json()) == (409, {"detail": "nothing_to_retry"})
    with psycopg.connect(db_url) as conn:
        rows = conn.execute("SELECT state, error FROM source_revisions").fetchall()
    assert rows == [("failed", "too_large")]


def test_manual_run_is_picked_up_only_when_the_worker_starts_it(
    make_api: Callable[..., TestClient],
    db_url: str,
    tmp_path: Path,
    make_fake_ollama: Callable[[], FakeOllama],
) -> None:
    fake = make_fake_ollama()
    VaultBuilder(tmp_path).write("a.md", "x")
    seed(db_url, tmp_path, fake.url)
    client = make_api(vault_path=str(tmp_path))
    assert client.get("/api/sources/summary").json()["last_run"]["picked_up_at"] is not None
    run_id = client.post("/api/sources/reconcile", headers=SAME_ORIGIN).json()["run_id"]
    queued = client.get("/api/sources/summary").json()["last_run"]
    assert (queued["trigger"], queued["finished_at"], queued["picked_up_at"]) == (
        "manual",
        None,
        None,
    )

    async def work() -> None:  # the worker picks the job up
        async with ingest_harness(db_url, tmp_path, fake.url, fresh=False) as h:
            await reconcile(h.ctx, trigger="manual", run_id=run_id)

    run_async(work())
    done = client.get("/api/sources/summary").json()["last_run"]
    assert done["picked_up_at"] is not None and done["finished_at"] is not None


class _BusyQueue:
    async def reconcile(self, run_id: int) -> bool:
        return False  # a reconcile job is already waiting


def test_reconcile_already_queued_is_409_and_finishes_the_run(
    make_api: Callable[..., TestClient], db_url: str, tmp_path: Path
) -> None:
    client = make_api(vault_path=str(tmp_path))
    client.app.state.ingest.queue = _BusyQueue()  # type: ignore[attr-defined]
    response = client.post("/api/sources/reconcile", headers=SAME_ORIGIN)
    assert (response.status_code, response.json()) == (409, {"detail": "scan_already_queued"})
    with psycopg.connect(db_url) as conn:
        rows = conn.execute("SELECT outcome, finished_at IS NOT NULL FROM ingest_runs").fetchall()
    assert rows == [("error:already_queued", True)]

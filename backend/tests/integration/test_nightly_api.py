from collections.abc import Callable, Iterator
from contextlib import ExitStack
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from ai_second_brain.config import Settings
from ai_second_brain.interfaces.api.app import create_app

from ..conftest import SAME_ORIGIN, TEST_PASSWORD, make_client

pytestmark = pytest.mark.integration

EVIL = {"Origin": "http://evil.example"}


@pytest.fixture
def db(db_url: str) -> Iterator[None]:
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(
            "TRUNCATE auth_sessions, sources, ingest_runs, procrastinate_jobs,"
            " entities, edges, nightly_runs CASCADE"
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


def insert(db_url: str, run_date: str, trigger: str, status: str) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO nightly_runs (run_date, trigger, status, window_start, finished_at)"
            " VALUES (%s, %s, %s, '-infinity', CASE WHEN %s = 'running' THEN NULL ELSE now() END)",
            (run_date, trigger, status, status),
        )


def test_digest_empty_returns_null_run(make_api: Callable[..., TestClient]) -> None:
    client = make_api()
    resp = client.get("/api/digest")
    assert resp.status_code == 200
    assert resp.json() == {
        "nightly_at": "02:00",
        "nightly_enabled": True,
        "run": None,
        "review": None,
        "failed": None,
        "indexed": None,
    }


def test_start_run_then_digest(make_api: Callable[..., TestClient]) -> None:
    client = make_api()
    resp = client.post("/api/nightly/run", headers=SAME_ORIGIN)
    assert resp.status_code == 202
    run = resp.json()["run"]
    assert run["trigger"] == "manual" and run["window_start"] is None
    digest = client.get("/api/digest").json()
    assert digest["run"]["id"] == run["id"]
    assert digest["run"]["status"] in ("running", "complete")
    assert digest["review"]["remaining"] == 0
    assert digest["failed"] == {"count": 0, "items": []}
    assert digest["indexed"]["since_beginning"] is True
    assert digest["nightly_at"] == "02:00"


def test_second_start_while_running_is_409(
    make_api: Callable[..., TestClient], db_url: str
) -> None:
    client = make_api()
    insert(db_url, "2026-10-04", "schedule", "running")
    resp = client.post("/api/nightly/run", headers=SAME_ORIGIN)
    assert resp.status_code == 409 and resp.json() == {"detail": "nightly_busy"}


def test_digest_by_date_404_and_422(make_api: Callable[..., TestClient], db_url: str) -> None:
    client = make_api()
    insert(db_url, "2026-10-04", "schedule", "complete")
    found = client.get("/api/digest/2026-10-04")
    assert found.status_code == 200 and found.json()["run"]["run_date"] == "2026-10-04"
    missing = client.get("/api/digest/2026-10-05")
    assert missing.status_code == 404 and missing.json() == {"detail": "not_found"}
    assert client.get("/api/digest/not-a-date").status_code == 422


def test_runs_list_order_and_limit(make_api: Callable[..., TestClient], db_url: str) -> None:
    client = make_api()
    insert(db_url, "2026-10-01", "schedule", "complete")
    insert(db_url, "2026-10-02", "schedule", "complete")
    insert(db_url, "2026-10-03", "manual", "failed")
    runs = client.get("/api/nightly/runs").json()["runs"]
    assert [r["run_date"] for r in runs] == ["2026-10-03", "2026-10-02", "2026-10-01"]
    assert runs[0]["trigger"] == "manual" and runs[0]["remaining"] == 0
    assert len(client.get("/api/nightly/runs?limit=2").json()["runs"]) == 2
    assert client.get("/api/nightly/runs?limit=0").status_code == 422
    assert client.get("/api/nightly/runs?limit=366").status_code == 422


def test_start_requires_same_origin(make_api: Callable[..., TestClient]) -> None:
    client = make_api()
    assert client.post("/api/nightly/run", headers=EVIL).status_code == 403
    assert client.get("/api/digest").json()["run"] is None  # nothing started


def test_start_without_queue_is_503(
    make_api: Callable[..., TestClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    client = make_api()

    async def no_queue() -> None:
        return None

    monkeypatch.setattr(client.app.state.ingest, "get_queue", no_queue)  # type: ignore[attr-defined]
    resp = client.post("/api/nightly/run", headers=SAME_ORIGIN)
    assert resp.status_code == 503 and resp.json() == {"detail": "database_unavailable"}


def test_routes_require_session(make_api: Callable[..., TestClient]) -> None:
    client = make_api(login=False)
    assert client.get("/api/digest").status_code == 401
    assert client.get("/api/digest/2026-10-04").status_code == 401
    assert client.get("/api/nightly/runs").status_code == 401
    assert client.post("/api/nightly/run", headers=SAME_ORIGIN).status_code == 401


def test_digest_read_closes_a_drained_run(make_api: Callable[..., TestClient], db_url: str) -> None:
    client = make_api()
    insert(db_url, "2026-10-04", "manual", "running")
    with psycopg.connect(db_url, autocommit=True) as conn:
        # its one job has run: nothing waits on the extract queue
        conn.execute("UPDATE nightly_runs SET queued_new = 1")
    digest = client.get("/api/digest").json()
    assert digest["run"]["status"] == "complete" and digest["run"]["timed_out"] is False


def test_digest_read_leaves_a_queueing_run_open(
    make_api: Callable[..., TestClient], db_url: str
) -> None:
    client = make_api()
    insert(db_url, "2026-10-04", "manual", "running")  # zero counts, just started
    assert client.get("/api/digest").json()["run"]["status"] == "running"
    assert client.get("/api/digest/2026-10-04").json()["run"]["status"] == "running"

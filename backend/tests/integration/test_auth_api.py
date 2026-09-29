import logging
import os
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient

from ai_second_brain.auth.sessions import token_id
from ai_second_brain.config import Settings
from ai_second_brain.interfaces.api.app import create_app

from ..conftest import SAME_ORIGIN, TEST_PASSWORD, make_client

pytestmark = pytest.mark.integration


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def db_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail("TEST_DATABASE_URL is not set. Run tests with `just test` from the repo root.")
    return url


@pytest.fixture
def db(db_url: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("TRUNCATE auth_sessions")
        yield conn


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def settings(make_settings: Callable[..., Settings], db_url: str) -> Settings:
    return make_settings(DATABASE_URL=db_url)


@pytest.fixture
def client(settings: Settings, clock: FakeClock, db: psycopg.Connection) -> Iterator[TestClient]:
    with make_client(create_app(settings, clock=clock)) as test_client:
        yield test_client


def login(client: TestClient, password: str = TEST_PASSWORD, **headers: str):
    return client.post(
        "/api/auth/login", json={"password": password}, headers=headers or SAME_ORIGIN
    )


def session_count(db: psycopg.Connection) -> int:
    row = db.execute("SELECT count(*) FROM auth_sessions").fetchone()
    assert row is not None
    return row[0]


def test_login_sets_cookie_and_me_works(client: TestClient, db: psycopg.Connection) -> None:
    response = login(client)
    assert response.status_code == 204
    cookie_header = response.headers["set-cookie"].lower()
    for attribute in ("httponly", "samesite=strict", "path=/api", "max-age=1209600"):
        assert attribute in cookie_header
    assert "secure" not in cookie_header
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["authenticated"] is True
    assert session_count(db) == 1


def test_only_token_hash_is_stored(client: TestClient, db: psycopg.Connection) -> None:
    login(client)
    token = client.cookies["sb_session"]
    row = db.execute("SELECT id FROM auth_sessions").fetchone()
    assert row is not None
    assert bytes(row[0]) == token_id(token)
    assert token.encode() not in bytes(row[0])


def test_wrong_password_is_401_and_creates_no_session(
    client: TestClient, db: psycopg.Connection
) -> None:
    response = login(client, "wrong")
    assert response.status_code == 401
    assert response.json() == {"detail": "invalid_credentials"}
    assert session_count(db) == 0


def test_sixth_rapid_failure_is_throttled(client: TestClient) -> None:
    for _ in range(5):
        assert login(client, "wrong").status_code == 401
    response = login(client, "wrong")
    assert response.status_code == 429
    assert response.json() == {"detail": "too_many_attempts"}
    assert 1 <= int(response.headers["retry-after"]) <= 60
    assert login(client).status_code == 429  # even the right password waits


def test_cross_origin_and_headerless_login_rejected(client: TestClient) -> None:
    assert login(client, **{"Origin": "http://evil.example"}).status_code == 403
    response = client.post("/api/auth/login", json={"password": TEST_PASSWORD})
    assert response.status_code == 403
    assert response.json() == {"detail": "cross_origin"}


@pytest.mark.parametrize(
    "body",
    [
        {"password": "x" * 1_000_000},
        {"password": ""},
        {},
        {"password": TEST_PASSWORD, "extra": 1},
    ],
)
def test_invalid_login_bodies_are_422_and_not_counted(client: TestClient, body: object) -> None:
    for _ in range(6):
        response = client.post("/api/auth/login", json=body, headers=SAME_ORIGIN)
        assert response.status_code == 422
        assert response.json() == {"detail": "invalid_request"}
    assert login(client).status_code == 204  # throttle untouched


def test_non_json_login_body_is_422(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        content=b"password=hunter2",
        headers={**SAME_ORIGIN, "Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("cookie", ["", "not-a-token", "x" * 5000, "%%%;;;"])
def test_garbage_cookies_are_401_not_500(client: TestClient, cookie: str) -> None:
    response = client.get("/api/auth/me", headers={"Cookie": f"sb_session={cookie}"})
    assert response.status_code == 401
    assert response.json() == {"detail": "not_authenticated"}


def test_logout_revokes_and_is_idempotent(client: TestClient, db: psycopg.Connection) -> None:
    login(client)
    token = client.cookies["sb_session"]
    response = client.post("/api/auth/logout", headers=SAME_ORIGIN)
    assert response.status_code == 204
    assert session_count(db) == 0
    client.cookies.clear()
    assert client.get("/api/auth/me").status_code == 401
    replay = client.get("/api/auth/me", headers={"Cookie": f"sb_session={token}"})
    assert replay.status_code == 401
    assert client.post("/api/auth/logout", headers=SAME_ORIGIN).status_code == 204


def test_expired_session_rejected_and_purged_on_startup(
    settings: Settings, clock: FakeClock, client: TestClient, db: psycopg.Connection
) -> None:
    login(client)
    clock.now += timedelta(days=15)
    assert client.get("/api/auth/me").status_code == 401
    with make_client(create_app(settings, clock=clock)):
        pass
    assert session_count(db) == 0


def test_touch_slides_expiry_at_most_every_five_minutes(
    client: TestClient, clock: FakeClock, db: psycopg.Connection
) -> None:
    login(client)
    start = clock.now

    def last_seen() -> datetime:
        row = db.execute("SELECT last_seen_at FROM auth_sessions").fetchone()
        assert row is not None
        return row[0]

    clock.now = start + timedelta(minutes=1)
    assert client.get("/api/auth/me").status_code == 200
    assert last_seen() == start
    clock.now = start + timedelta(minutes=6)
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert last_seen() == clock.now
    assert datetime.fromisoformat(me.json()["expires_at"]) == clock.now + timedelta(days=14)
    assert "max-age=1209600" in me.headers["set-cookie"].lower()


def test_logs_never_contain_password_or_token(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    login(client)
    token = client.cookies["sb_session"]
    client.get("/api/auth/me")
    assert TEST_PASSWORD not in caplog.text
    assert token not in caplog.text
    assert "POST /api/auth/login 204" in caplog.text


def test_login_and_me_are_503_when_database_down(
    make_settings: Callable[..., Settings],
) -> None:
    with make_client(create_app(make_settings())) as dead:  # default settings point at port 1
        response = dead.post(
            "/api/auth/login", json={"password": TEST_PASSWORD}, headers=SAME_ORIGIN
        )
        assert response.status_code == 503
        assert response.json() == {"detail": "database_unavailable"}
        me = dead.get("/api/auth/me", headers={"Cookie": "sb_session=some-token"})
        assert me.status_code == 503


def test_concurrent_wrong_passwords_cannot_exceed_throttle(client: TestClient) -> None:
    def attempt(_: int) -> tuple[int, dict[str, str]]:
        response = client.post("/api/auth/login", json={"password": "wrong"}, headers=SAME_ORIGIN)
        return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(attempt, range(10)))
    statuses = [status for status, _ in results]
    assert statuses.count(401) <= 5
    assert statuses.count(401) + statuses.count(429) == 10
    assert all(body == {"detail": "too_many_attempts"} for status, body in results if status == 429)

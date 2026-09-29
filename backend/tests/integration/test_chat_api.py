import threading
import time
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from ai_second_brain.chat.providers.base import ChatTimeouts
from ai_second_brain.config import Settings
from ai_second_brain.interfaces.api.app import create_app

from ..conftest import SAME_ORIGIN, TEST_PASSWORD, make_client
from ..fakes.ollama import FakeOllama
from ..fakes.sse import parse_sse

pytestmark = pytest.mark.integration

FAST = ChatTimeouts(connect=1.0, read=1.0, probe=0.5)
EVIL = {"Origin": "https://evil.example"}
ClientFactory = Callable[..., TestClient]


@pytest.fixture
def db(db_url: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("TRUNCATE auth_sessions, chat_sessions CASCADE")
        yield conn


@pytest.fixture
def make_chat_client(
    make_settings: Callable[..., Settings], db_url: str, db: psycopg.Connection
) -> Iterator[ClientFactory]:
    with ExitStack() as stack:

        def _make(*, login: bool = True, **settings: Any) -> TestClient:
            app = create_app(make_settings(DATABASE_URL=db_url, **settings), chat_timeouts=FAST)
            client = stack.enter_context(make_client(app))
            if login:
                response = client.post(
                    "/api/auth/login", json={"password": TEST_PASSWORD}, headers=SAME_ORIGIN
                )
                assert response.status_code == 204
            return client

        yield _make


def endpoints(*fakes: FakeOllama) -> list[dict[str, Any]]:
    return [
        {"label": f"ep{i}", "url": fake.url, "model": "fake-model"} for i, fake in enumerate(fakes)
    ]


def create(client: TestClient, mode: str = "private") -> dict[str, Any]:
    response = client.post("/api/sessions", json={"mode": mode}, headers=SAME_ORIGIN)
    assert response.status_code == 201, response.text
    return response.json()


def ask(client: TestClient, session_id: str, question: str = "What is Proxmox?"):
    return client.post(
        f"/api/sessions/{session_id}/turns", json={"question": question}, headers=SAME_ORIGIN
    )


def test_create_defaults_to_private_and_cloud_needs_a_key(
    make_chat_client: ClientFactory,
) -> None:
    client = make_chat_client()
    response = client.post("/api/sessions", json={}, headers=SAME_ORIGIN)
    assert response.status_code == 201
    assert response.json()["mode"] == "private"
    refused = client.post("/api/sessions", json={"mode": "cloud"}, headers=SAME_ORIGIN)
    assert (refused.status_code, refused.json()) == (409, {"detail": "cloud_unavailable"})
    cloud_client = make_chat_client(anthropic_api_key="sk-test")
    assert create(cloud_client, "cloud")["mode"] == "cloud"


def test_private_turn_streams_and_is_saved(
    make_chat_client: ClientFactory, make_fake_ollama: Callable[[], FakeOllama]
) -> None:
    fake = make_fake_ollama()
    client = make_chat_client(ollama_endpoints=endpoints(fake))
    session = create(client)
    response = ask(client, session["id"])
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-accel-buffering"] == "no"
    names = [name for name, _ in parse_sse(response.text)]
    assert names == [
        "status",
        "sources",
        "status",
        "status",
        "token",
        "token",
        "token",
        "receipt",
        "done",
    ]
    detail = client.get(f"/api/sessions/{session['id']}").json()
    assert detail["title"] == "What is Proxmox?"
    [turn] = detail["turns"]
    assert (turn["answer"], turn["endpoint"], turn["model"]) == (
        "Hello from Ollama",
        "ep0",
        "fake-model",
    )


def test_list_get_delete(
    make_chat_client: ClientFactory, make_fake_ollama: Callable[[], FakeOllama]
) -> None:
    fake = make_fake_ollama()
    client = make_chat_client(ollama_endpoints=endpoints(fake))
    older, newer = create(client), create(client)
    ask(client, older["id"])
    ids = [s["id"] for s in client.get("/api/sessions").json()]
    assert ids.index(older["id"]) < ids.index(newer["id"])
    assert client.delete(f"/api/sessions/{older['id']}", headers=SAME_ORIGIN).status_code == 204
    assert client.get(f"/api/sessions/{older['id']}").json() == {"detail": "not_found"}
    assert client.delete(f"/api/sessions/{older['id']}", headers=SAME_ORIGIN).status_code == 404
    assert client.get("/api/sessions/not-a-uuid").status_code == 422


def test_unknown_session_turn_is_404(make_chat_client: ClientFactory) -> None:
    client = make_chat_client()
    response = ask(client, "00000000-0000-4000-8000-000000000000")
    assert (response.status_code, response.json()) == (404, {"detail": "not_found"})


def test_mode_cannot_change(make_chat_client: ClientFactory) -> None:
    client = make_chat_client(anthropic_api_key="sk-test")
    session = create(client)
    for method in ("PATCH", "PUT"):
        response = client.request(
            method, f"/api/sessions/{session['id']}", json={"mode": "cloud"}, headers=SAME_ORIGIN
        )
        assert response.status_code == 405
    assert client.get(f"/api/sessions/{session['id']}").json()["mode"] == "private"


def test_question_validation(
    make_chat_client: ClientFactory, make_fake_ollama: Callable[[], FakeOllama]
) -> None:
    fake = make_fake_ollama()
    client = make_chat_client(ollama_endpoints=endpoints(fake))
    session = create(client)
    for bad in ("", "   \n\t", "x" * 8001):
        response = ask(client, session["id"], bad)
        assert (response.status_code, response.json()) == (422, {"detail": "invalid_request"})
    assert fake.requests == []  # nothing was contacted for invalid questions
    assert ask(client, session["id"], "y" * 8000).status_code == 200


def test_csrf_and_login_are_enforced(make_chat_client: ClientFactory) -> None:
    client = make_chat_client()
    session = create(client)
    assert client.post("/api/sessions", json={}, headers=EVIL).status_code == 403
    assert client.delete(f"/api/sessions/{session['id']}", headers=EVIL).status_code == 403
    turn = client.post(f"/api/sessions/{session['id']}/turns", json={"question": "q"}, headers=EVIL)
    assert turn.status_code == 403
    anonymous = make_chat_client(login=False)
    for method, path in [
        ("GET", "/api/chat/status"),
        ("GET", "/api/sessions"),
        ("POST", "/api/sessions"),
        ("GET", f"/api/sessions/{session['id']}"),
        ("DELETE", f"/api/sessions/{session['id']}"),
        ("POST", f"/api/sessions/{session['id']}/turns"),
    ]:
        response = anonymous.request(method, path, json={"question": "q"}, headers=SAME_ORIGIN)
        assert response.status_code == 401, (method, path)


def test_status_reports_endpoints_and_cloud(
    make_chat_client: ClientFactory, make_fake_ollama: Callable[[], FakeOllama]
) -> None:
    up, down = make_fake_ollama(), make_fake_ollama()
    down.behaviour.probe_status = 503
    client = make_chat_client(ollama_endpoints=endpoints(down, up))
    body = client.get("/api/chat/status").json()
    assert body == {
        "private": {
            "available": True,
            "endpoints": [
                {"label": "ep0", "model": "fake-model", "degraded": False, "reachable": False},
                {"label": "ep1", "model": "fake-model", "degraded": False, "reachable": True},
            ],
        },
        "cloud": {"available": False, "model": None},
    }
    cloud = make_chat_client(anthropic_api_key="sk", anthropic_model="claude-x")
    assert cloud.get("/api/chat/status").json()["cloud"] == {"available": True, "model": "claude-x"}
    assert cloud.get("/api/chat/status").json()["private"] == {"available": False, "endpoints": []}


def test_second_turn_while_streaming_is_409(
    make_chat_client: ClientFactory, make_fake_ollama: Callable[[], FakeOllama]
) -> None:
    fake = make_fake_ollama()
    fake.behaviour.first_chunk_delay = 0.8
    client = make_chat_client(ollama_endpoints=endpoints(fake))
    session = create(client)
    first: dict[str, Any] = {}
    thread = threading.Thread(target=lambda: first.update(r=ask(client, session["id"])))
    thread.start()
    time.sleep(0.3)
    second = ask(client, session["id"])
    thread.join(timeout=10)
    assert (second.status_code, second.json()) == (409, {"detail": "turn_in_progress"})
    assert first["r"].status_code == 200

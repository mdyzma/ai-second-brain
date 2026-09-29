import os
from collections.abc import Callable, Coroutine, Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_second_brain.auth.passwords import hash_password
from ai_second_brain.config import Settings
from ai_second_brain.runtime import new_event_loop

from .fakes.ollama import FakeOllama

TEST_PASSWORD = "correct horse battery staple"
TEST_HASH = hash_password(TEST_PASSWORD)
SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}
UNUSED_DB = "postgres://brain:brain@127.0.0.1:1/unused?connect_timeout=1"


def make_client(app: FastAPI) -> TestClient:
    """TestClient on a selector event loop (required by psycopg async on Windows)."""
    return TestClient(app, backend_options={"loop_factory": new_event_loop})


def run_async[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine on a fresh selector loop (psycopg async needs one on Windows)."""
    loop = new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture(autouse=True)
def isolate_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the developer's .env (exported by just) from leaking into tests.

    TEST_DATABASE_URL stays: the integration tests read it deliberately.
    """
    for name in list(os.environ):
        if name.startswith("SB_") or name == "DATABASE_URL" or name.lower().endswith("_proxy"):
            monkeypatch.delenv(name)


@pytest.fixture
def make_settings() -> Callable[..., Settings]:
    def _make(**overrides: Any) -> Settings:
        values: dict[str, Any] = {
            "DATABASE_URL": UNUSED_DB,
            "owner_password_hash": TEST_HASH,
            "allowed_origins": "http://localhost:5173",
        }
        values.update(overrides)
        return Settings(_env_file=None, **values)  # pyright: ignore[reportCallIssue]

    return _make


@pytest.fixture
def make_fake_ollama() -> Iterator[Callable[[], FakeOllama]]:
    started: list[FakeOllama] = []

    def _make() -> FakeOllama:
        fake = FakeOllama().start()
        started.append(fake)
        return fake

    yield _make
    for fake in started:
        fake.stop()

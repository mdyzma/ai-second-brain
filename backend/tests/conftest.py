from collections.abc import Callable
from typing import Any

import pytest

from ai_second_brain.auth.passwords import hash_password
from ai_second_brain.config import Settings

TEST_PASSWORD = "correct horse battery staple"
TEST_HASH = hash_password(TEST_PASSWORD)
SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}
UNUSED_DB = "postgres://brain:brain@127.0.0.1:1/unused?connect_timeout=1"


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

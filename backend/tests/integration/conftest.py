import os

import pytest


@pytest.fixture
def db_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail("TEST_DATABASE_URL is not set. Run tests with `just test` from the repo root.")
    return url

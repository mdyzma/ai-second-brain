import os

import pytest

from ..eval_db import eval_db_url  # noqa: F401  (fixture)


@pytest.fixture
def db_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail("TEST_DATABASE_URL is not set. Run tests with `just test` from the repo root.")
    return url

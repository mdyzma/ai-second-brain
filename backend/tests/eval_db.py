"""Create `<test db>_eval` from db/schema.sql plus the eval-only migration (no dbmate needed)."""

import re
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]
EVAL_MIGRATION = ROOT / "db" / "eval" / "migrations" / "20261002100000_eval_cache.sql"


def _with_db(url: str, name: str) -> str:
    return urlunsplit(urlsplit(url)._replace(path=f"/{name}"))


def eval_db_name(db_url: str) -> str:
    """The scratch database's name: always `<test db>_eval`, never anything else."""
    test_name = urlsplit(db_url).path.lstrip("/")
    assert test_name, "TEST_DATABASE_URL has no database name"
    return test_name + "_eval"


@pytest.fixture
def eval_db_url(db_url: str) -> Iterator[str]:
    test_name = urlsplit(db_url).path.lstrip("/")
    name = eval_db_name(db_url)
    # The only database this fixture may ever drop: derived from the test URL, `_eval`-suffixed.
    assert name == f"{test_name}_eval" and name.endswith("_eval") and name != test_name
    with psycopg.connect(_with_db(db_url, "postgres"), autocommit=True) as admin:
        drop = sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
        admin.execute(drop)
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = _with_db(db_url, name)
    schema = (ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
    up = re.split(r"--\s*migrate:down", EVAL_MIGRATION.read_text(encoding="utf-8"))[0]
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(schema)  # type: ignore[arg-type]
    with psycopg.connect(url, autocommit=True) as conn:  # schema.sql empties search_path
        conn.execute(up)  # type: ignore[arg-type]
        conn.execute(
            "INSERT INTO embedding_spaces (id, model, dims, is_default)"
            " VALUES (1, 'bge-m3', 1024, true) ON CONFLICT DO NOTHING"
        )
    yield url

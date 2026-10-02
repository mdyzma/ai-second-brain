"""Create `<test db>_eval` from db/schema.sql plus the eval-only migration (no dbmate needed)."""

import re
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg
import pytest
from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]
EVAL_MIGRATION = ROOT / "db" / "eval" / "migrations" / "20261002100000_eval_cache.sql"


def _with_db(url: str, name: str) -> str:
    """`url` pointed at database `name`; a `?dbname=` parameter can't redirect it elsewhere."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "dbname"]
    return urlunsplit(parts._replace(path=f"/{name}", query=urlencode(query)))


def eval_db_name(db_url: str) -> str:
    """The scratch database's name: always `<test db>_eval`, never anything else."""
    test_name = urlsplit(db_url).path.lstrip("/")
    if not test_name or "/" in test_name:
        raise RuntimeError("TEST_DATABASE_URL must name its database in the URL path")
    return test_name + "_eval"


@pytest.fixture
def eval_db_url(db_url: str) -> Iterator[str]:
    # The only database this fixture may ever drop: derived from the test URL, `_eval`-suffixed.
    # An explicit raise (not assert) so the check also runs under `python -O`.
    name = eval_db_name(db_url)
    if not name.endswith("_eval"):
        raise RuntimeError("refusing to drop a database whose name does not end in _eval")
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

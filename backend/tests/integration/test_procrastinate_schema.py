from pathlib import Path

import pytest
from procrastinate.schema import SchemaManager

from ai_second_brain.config import REPO_ROOT
from ai_second_brain.knowledge.jobs import create_job_app

from ..conftest import run_async

pytestmark = pytest.mark.integration

MIGRATION = REPO_ROOT / "db" / "migrations" / "20260930100000_procrastinate.sql"


def vendored_up_sql(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    up = text.split("-- migrate:up", 1)[1].split("-- migrate:down", 1)[0]
    comment_prefixes = ("-- Vendored", "-- Upgrading")
    body = [line for line in up.splitlines() if not line.startswith(comment_prefixes)]
    return "\n".join(body).strip()


def test_vendored_schema_matches_installed_procrastinate() -> None:
    assert vendored_up_sql(MIGRATION) == SchemaManager.get_schema().strip()


def test_job_app_registers_ingest_tasks(db_url: str) -> None:
    app = create_job_app(db_url)
    expected = {"ingest:index_source", "ingest:embed_revision", "ingest:reconcile_vault"}
    assert expected <= set(app.tasks)

    async def scenario() -> None:
        async with app.open_async():
            assert await app.check_connection_async()

    run_async(scenario())

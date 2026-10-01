import json
import re
from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest

from ai_second_brain.search.tags import normalise_tags
from ai_second_brain.vault.reconcile import reconcile

from ..conftest import run_async
from ..fakes.ollama import FakeOllama
from ..ingest_harness import ingest_harness
from ..unit.test_search_pure import TAG_CASES
from ..vaults import VaultBuilder

pytestmark = pytest.mark.integration
MIGRATION = Path(__file__).parents[3] / "db" / "migrations" / "20261001120000_search.sql"


def sql_function() -> str:
    text = MIGRATION.read_text(encoding="utf-8")
    match = re.search(r"-- begin sb_normalise_tags.*?\n(.*?)-- end sb_normalise_tags", text, re.S)
    assert match
    return match.group(1)


@pytest.mark.parametrize(("value", "expected"), TAG_CASES)
def test_sql_backfill_matches_python(db_url: str, value: object, expected: list[str]) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(sql_function())  # type: ignore[call-overload]  # pg_temp: per connection
        row = conn.execute(
            "SELECT pg_temp.sb_normalise_tags(%s::jsonb)", (json.dumps(value),)
        ).fetchone()
    assert row is not None
    assert row[0] == expected == normalise_tags(value)


def test_index_writes_tags(
    db_url: str, tmp_path: Path, make_fake_ollama: Callable[[], FakeOllama]
) -> None:
    fake = make_fake_ollama()
    VaultBuilder(tmp_path).write("a.md", "---\ntags: [Homelab, '#nas']\n---\n# A\nx")

    async def scenario() -> None:
        async with ingest_harness(db_url, tmp_path, fake.url) as h:
            await reconcile(h.ctx, trigger="startup")
            await h.drain()
            [row] = await h.rows(
                "SELECT r.tags FROM sources s"
                " JOIN source_revisions r ON r.id = s.current_revision_id"
            )
            assert row["tags"] == ["homelab", "nas"]

    run_async(scenario())


def test_headings_and_title_are_full_text_searchable(
    db_url: str, tmp_path: Path, make_fake_ollama: Callable[[], FakeOllama]
) -> None:
    fake = make_fake_ollama()
    VaultBuilder(tmp_path).write("NAS.md", "# NAS\n## Kopie zapasowe\nCo noc o 02:00.")
    VaultBuilder(tmp_path).write("No heading.md", "just body text")

    async def scenario() -> None:
        async with ingest_harness(db_url, tmp_path, fake.url) as h:
            await reconcile(h.ctx, trigger="startup")
            await h.drain()
            rows = await h.rows("SELECT c.heading_text FROM chunks c ORDER BY c.heading_text")
            assert [r["heading_text"] for r in rows] == ["NAS Kopie zapasowe", "No heading"]
            [hit] = await h.rows(
                "SELECT count(*) AS n FROM chunks"
                " WHERE tsv @@ websearch_to_tsquery('simple', 'zapasowe')"
            )
            assert hit["n"] == 1

    run_async(scenario())

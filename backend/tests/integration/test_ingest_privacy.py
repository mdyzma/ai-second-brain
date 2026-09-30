"""Spec §10.3 #12: ingestion never logs note text, titles or paths, and job args are ids only."""

import logging
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

import pytest

from ai_second_brain.vault.batch import apply_batch
from ai_second_brain.vault.reconcile import reconcile

from ..conftest import run_async
from ..fakes.ollama import FakeOllama
from ..ingest_harness import Harness, ingest_harness
from ..vaults import VaultBuilder

pytestmark = pytest.mark.integration

FOLDER = "Tajny-Projekt-Zebra"
NOTE = f"{FOLDER}/Sekretna-Notatka-Kwarc.md"
MOVED = f"{FOLDER}/Przeniesiona-Notatka-Onyks.md"
OTHER = "Prywatny-Dziennik-Bursztyn.md"
SECRETS = [
    "Tajny-Projekt-Zebra",
    "Sekretna-Notatka-Kwarc",
    "Przeniesiona-Notatka-Onyks",
    "Prywatny-Dziennik-Bursztyn",
    "Obsydianowy-Szafir",  # a title
    "Lazurowy-Kormoran",  # body text
    "Purpurowy-Wieloryb",  # edited body text
    "Miedziany-Tukan",  # frontmatter
]


def test_ingestion_logs_and_job_args_carry_no_note_content(
    db_url: str,
    tmp_path: Path,
    make_fake_ollama: Callable[[], FakeOllama],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.DEBUG, logger="procrastinate")
    caplog.set_level(logging.DEBUG, logger="ai_second_brain")
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write(NOTE, "---\ntag: Miedziany-Tukan\n---\n# Obsydianowy-Szafir\nLazurowy-Kormoran\n")
    vault.write(OTHER, "# Prywatny-Dziennik-Bursztyn\nLazurowy-Kormoran w dzienniku\n")

    async def body(h: Harness) -> None:
        await reconcile(h.ctx, trigger="startup")  # observe + index jobs
        await h.drain()  # index + embed
        vault.rename(NOTE, MOVED)  # watcher batch: a move
        await apply_batch(h.ctx, [("deleted", NOTE), ("added", MOVED)])
        vault.write(MOVED, "# Obsydianowy-Szafir\nPurpurowy-Wieloryb\n")  # an edit
        await apply_batch(h.ctx, [("modified", MOVED)])
        fake.behaviour.embed_status = 503  # a retryable failure: procrastinate logs the error
        await h.drain()
        fake.behaviour.embed_status = 404  # a permanent failure records a code
        fake.behaviour.embed_error_text = "model not found"
        await reconcile(h.ctx, trigger="schedule")
        await h.drain()
        vault.delete(OTHER)  # a delete
        await apply_batch(h.ctx, [("deleted", OTHER)])
        await reconcile(h.ctx, trigger="schedule")
        await h.drain()
        jobs = await h.rows("SELECT task_name, args FROM procrastinate_jobs")
        assert {j["task_name"] for j in jobs} >= {"ingest:index_source", "ingest:embed_revision"}
        for job in jobs:
            for value in job["args"].values():
                if isinstance(value, str):
                    UUID(value)  # raises unless the string is a UUID
                else:
                    assert isinstance(value, int) and not isinstance(value, bool)

    async def scenario() -> None:
        async with ingest_harness(db_url, tmp_path, fake.url) as h:
            await body(h)

    run_async(scenario())
    assert "index source=" in caplog.text  # the scenarios did log
    assert any(r.name.startswith("procrastinate") for r in caplog.records)
    assert any(r.exc_info for r in caplog.records)  # a job error with its traceback
    leaked = [secret for secret in SECRETS if secret in caplog.text]
    assert leaked == []

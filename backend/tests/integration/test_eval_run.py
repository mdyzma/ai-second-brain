import json
import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from ai_second_brain.chat.providers.ollama import create_http_client
from ai_second_brain.config import Settings
from ai_second_brain.eval import runner
from ai_second_brain.eval.embedding import ModelEmbedError
from ai_second_brain.eval.queries import EvalConfigError
from ai_second_brain.eval.report import write_report
from ai_second_brain.eval.runner import RunResult, run_eval
from ai_second_brain.interfaces.cli import main
from ai_second_brain.knowledge.embedder import EmbedError
from ai_second_brain.vault.reconcile import reconcile

from ..conftest import TEST_HASH, run_async
from ..fakes.ollama import FakeOllama
from ..ingest_harness import ingest_harness
from ..vaults import VaultBuilder

pytestmark = pytest.mark.integration

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "eval" / "queries.yaml"
FILLERS = 12
# bge-m3: the paraphrase and topic queries share a "decoy" vector with every filler chunk, so
# the 12 fillers fill the top 10 and NAS/Proxmox miss. good-model maps each query onto the
# chunk of its target note. "RAID 5" maps to nothing under either: text search finds NAS.
TOPICS = {
    "bge-m3": {"filler": "decoy", "backup": "decoy", "wirtualizacji": "decoy"},
    "good-model": {
        "backup": "backup",
        "kopie zapasowe": "backup",
        "wirtualizacji": "virt",
        "klaster": "virt",
    },
}


def _vault(root: Path) -> None:
    vault = VaultBuilder(root)
    vault.write(
        "Projects/NAS.md",
        "# NAS\n## Dyski\nCztery dyski w RAID 5.\n## Kopie zapasowe\nCo noc o 02:00.",
    )
    vault.write("Projects/Proxmox.md", "# Proxmox\nKlaster z jednym węzłem.")
    for i in range(FILLERS):
        vault.write(f"Filler/f{i}.md", f"# F{i}\nfiller text {i}")


def _settings(db_url: str, eval_db_url: str, tmp_path: Path, fake: FakeOllama) -> Settings:
    values: dict[str, Any] = {
        "DATABASE_URL": db_url,
        "owner_password_hash": TEST_HASH,
        "eval_dir": tmp_path / "reports",
        "SB_EVAL_DATABASE_URL": eval_db_url,
        "embed_url_override": fake.url,
    }
    return Settings(_env_file=None, **values)  # pyright: ignore[reportCallIssue]


def _run(
    db_url: str,
    eval_db_url: str,
    tmp_path: Path,
    fake: FakeOllama,
    queries_path: Path = FIXTURE,
    progress: Callable[[str], None] = lambda _: None,
) -> RunResult:
    vault_root = tmp_path / "vault"
    _vault(vault_root)
    settings = _settings(db_url, eval_db_url, tmp_path, fake)

    async def scenario() -> RunResult:
        async with ingest_harness(db_url, vault_root, fake.url) as h:
            await reconcile(h.ctx, trigger="startup")
            await h.drain()
        fake.behaviour.embed_topics_by_model = TOPICS
        async with create_http_client() as client:
            return await run_eval(
                settings,
                queries_path=queries_path,
                models=["bge-m3", "good-model"],
                dev_url=db_url,
                eval_url=eval_db_url,
                test_url=None,
                client=client,
                progress=progress,
            )

    return run_async(scenario())


def test_full_run_writes_report_and_picks_winner(  # type: ignore[no-untyped-def]
    db_url: str, eval_db_url: str, tmp_path: Path, make_fake_ollama
) -> None:
    fake = make_fake_ollama()
    result = _run(db_url, eval_db_url, tmp_path, fake)

    assert result.verdict.winner == "good-model"
    assert result.models[0].hybrid[1] == 1  # RAID 5 is found by text for both models
    assert result.models[1].hybrid[1] == 1
    assert result.models[1].hybrid[0] == 1
    assert result.models[0].hybrid[0] is None
    assert result.models[0].hybrid[2] is None
    assert result.models[1].hybrid[2] == 1
    assert result.snapshot.sources == 2 + FILLERS

    settings = _settings(db_url, eval_db_url, tmp_path, fake)
    folder = write_report(result, settings.eval_report_dir, datetime(2026, 10, 2, 12, 0, 0))
    assert folder.name == "20261002-120000"
    md = (folder / "report.md").read_text(encoding="utf-8")
    assert "good-model wins → Phase 3b" in md
    for query in yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))["queries"]:
        assert query["q"] not in md  # the report shows ids, never query text
    data = json.loads((folder / "results.json").read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert data["queries"][0]["runs"]["good-model"]["hybrid"][0] == "Projects/NAS.md"

    again = write_report(result, settings.eval_report_dir, datetime(2026, 10, 2, 12, 0, 0))
    assert again.name == "20261002-120000-2"


def test_run_refuses_dev_url(db_url: str, tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    values: dict[str, Any] = {
        "DATABASE_URL": db_url,
        "owner_password_hash": TEST_HASH,
        "eval_dir": reports,
        "embed_url_override": "http://127.0.0.1:9",
    }
    settings = Settings(_env_file=None, **values)  # pyright: ignore[reportCallIssue]

    async def scenario() -> None:
        async with create_http_client() as client:
            await run_eval(
                settings,
                queries_path=FIXTURE,
                models=["bge-m3"],
                dev_url=db_url,
                eval_url=db_url.replace("127.0.0.1", "localhost"),
                test_url=None,
                client=client,
                progress=lambda _: None,
            )

    with pytest.raises(EvalConfigError) as caught:
        run_async(scenario())
    assert "dev or test" in caught.value.errors[0]
    assert not reports.exists()


def test_missing_target_is_config_error(  # type: ignore[no-untyped-def]
    db_url: str, eval_db_url: str, tmp_path: Path, make_fake_ollama
) -> None:
    fake = make_fake_ollama()
    queries = tmp_path / "queries.yaml"
    queries.write_text(
        "version: 1\nqueries:\n"
        "  - {id: ghost-note, q: 'gdzie jest duch', lang: pl, kind: topic,"
        " targets: [Projects/Ghost.md]}\n"
        "  - {id: nas-ok, q: 'RAID 5', lang: en, kind: identifier, targets: [Projects/NAS.md]}\n",
        encoding="utf-8",
    )
    with pytest.raises(EvalConfigError) as caught:
        _run(db_url, eval_db_url, tmp_path, fake, queries)
    assert caught.value.errors == ["ghost-note: target not in the index: Projects/Ghost.md"]


def test_run_logs_no_query_text(  # type: ignore[no-untyped-def]
    db_url: str, eval_db_url: str, tmp_path: Path, make_fake_ollama, caplog
) -> None:
    caplog.set_level(logging.DEBUG)
    fake = make_fake_ollama()
    _run(db_url, eval_db_url, tmp_path, fake)
    assert "eval run models=2 queries=3" in caplog.text
    for query in yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))["queries"]:
        assert query["q"] not in caplog.text
        assert query["targets"][0] not in caplog.text


def test_suggest_round_robins_folders_and_check_reads_live_paths(  # type: ignore[no-untyped-def]
    db_url: str, eval_db_url: str, tmp_path: Path, make_fake_ollama
) -> None:
    fake = make_fake_ollama()
    vault_root = tmp_path / "vault"
    _vault(vault_root)
    VaultBuilder(vault_root).write("root.md", "# Root\nat the top")
    settings = _settings(db_url, eval_db_url, tmp_path, fake)

    async def scenario() -> tuple[list[str], list[str], set[str]]:
        async with ingest_harness(db_url, vault_root, fake.url) as h:
            await reconcile(h.ctx, trigger="startup")
            await h.drain()
        return (
            await main._suggest_paths(settings, 3),  # pyright: ignore[reportPrivateUsage]
            await main._suggest_paths(settings, 100),  # pyright: ignore[reportPrivateUsage]
            await main._dev_live_paths(settings),  # pyright: ignore[reportPrivateUsage]
        )

    three, everything, live = run_async(scenario())
    folders = {p.split("/")[0] if "/" in p else "" for p in three}
    assert folders == {"", "Filler", "Projects"}  # one pick per top-level folder first
    assert len(everything) == len(set(everything)) == 3 + FILLERS
    assert live == set(everything)


def test_mid_run_embed_failure_names_the_model(  # type: ignore[no-untyped-def]
    db_url: str, eval_db_url: str, tmp_path: Path, make_fake_ollama, monkeypatch
) -> None:
    fake = make_fake_ollama()
    real = runner.query_vectors

    async def flaky(embedder: Any, texts: Any) -> Any:
        if embedder.model == "good-model":
            raise EmbedError("embed_unreachable")
        return await real(embedder, texts)

    monkeypatch.setattr(runner, "query_vectors", flaky)
    with pytest.raises(ModelEmbedError) as caught:
        _run(db_url, eval_db_url, tmp_path, fake)
    assert (caught.value.code, caught.value.model) == ("embed_unreachable", "good-model")


def test_run_reports_progress_lines_and_query_prefix(  # type: ignore[no-untyped-def]
    db_url: str, eval_db_url: str, tmp_path: Path, make_fake_ollama
) -> None:
    fake = make_fake_ollama()
    lines: list[str] = []
    result = _run(db_url, eval_db_url, tmp_path, fake, progress=lines.append)
    assert lines and all(" chunks · " in line and "/s · ETA " in line for line in lines)
    assert lines[0].startswith("bge-m3 ")
    assert [run.query_prefix for run in result.models] == ["", ""]


def test_run_refuses_duplicate_models(db_url: str, eval_db_url: str, tmp_path: Path) -> None:
    settings = _settings(db_url, eval_db_url, tmp_path, FakeOllama())

    async def scenario() -> None:
        async with create_http_client() as client:
            await run_eval(
                settings,
                queries_path=FIXTURE,
                models=["bge-m3", "bge-m3"],
                dev_url=db_url,
                eval_url=eval_db_url,
                test_url=None,
                client=client,
                progress=lambda _: None,
            )

    with pytest.raises(EvalConfigError) as caught:
        run_async(scenario())
    assert caught.value.errors == ["duplicate model bge-m3"]

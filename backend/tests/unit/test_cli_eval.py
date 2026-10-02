from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from ai_second_brain.config import Settings
from ai_second_brain.eval.database import DbmateError
from ai_second_brain.eval.embedding import PreflightError
from ai_second_brain.eval.queries import EvalConfigError
from ai_second_brain.interfaces.cli import main
from ai_second_brain.interfaces.cli.main import app

from .test_eval_report import _result

runner = CliRunner()


@pytest.fixture
def settings(
    monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings], tmp_path: Path
) -> Settings:
    built = make_settings(
        eval_dir=tmp_path / "reports",
        eval_queries=tmp_path / "queries.yaml",
        embed_url_override="http://127.0.0.1:9",
    )
    monkeypatch.setattr(main, "get_settings", lambda: built)
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    return built


def _fake_run(outcome: Any) -> Callable[..., Any]:
    async def fake(*args: Any, **kwargs: Any) -> Any:
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    return fake


def test_run_prints_verdict_and_writes_report(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    monkeypatch.setattr(main, "run_eval", _fake_run(_result()))
    result = runner.invoke(app, ["eval", "run", "--models", "bge-m3,good-model"])
    assert result.exit_code == 0, result.output
    assert "good-model wins → Phase 3b" in result.stdout
    assert "recall@10" in result.stdout
    folders = list(settings.eval_report_dir.iterdir())
    assert len(folders) == 1
    assert (folders[0] / "report.md").is_file()
    assert str(folders[0]) in result.stdout


def test_run_config_error_exits_1(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    error = EvalConfigError(["a-id: target not in the index: X.md", "b-id: duplicate id"])
    monkeypatch.setattr(main, "run_eval", _fake_run(error))
    result = runner.invoke(app, ["eval", "run"])
    assert result.exit_code == 1
    assert "a-id: target not in the index: X.md" in result.stderr
    assert "b-id: duplicate id" in result.stderr
    assert not settings.eval_report_dir.exists()


def test_run_missing_model_exits_1(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    monkeypatch.setattr(main, "run_eval", _fake_run(PreflightError("embed_model_missing", "ghost")))
    result = runner.invoke(app, ["eval", "run"])
    assert result.exit_code == 1
    assert "Model ghost is not installed: run ollama pull ghost" in result.stderr


def test_run_other_preflight_code_exits_1(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    error = PreflightError("embed_unreachable", "bge-m3")
    monkeypatch.setattr(main, "run_eval", _fake_run(error))
    result = runner.invoke(app, ["eval", "run"])
    assert result.exit_code == 1
    assert "embed_unreachable" in result.stderr and "bge-m3" in result.stderr


def test_run_unexpected_error_exits_2(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    error = RuntimeError("secret note text")
    monkeypatch.setattr(main, "run_eval", _fake_run(error))
    result = runner.invoke(app, ["eval", "run"])
    assert result.exit_code == 2
    assert "Evaluation failed (RuntimeError)." in result.stderr
    assert "secret note text" not in result.output


def test_run_refuses_out_inside_repo(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    monkeypatch.setattr(main, "run_eval", _fake_run(_result()))
    result = runner.invoke(app, ["eval", "run", "--out", str(main.REPO_ROOT / "reports")])
    assert result.exit_code == 1
    assert "outside the repository" in result.stderr


def test_prepare_ok_and_dbmate_failure(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    calls: list[tuple[str, Path]] = []
    monkeypatch.setattr(main, "prepare_eval_db", lambda url, root: calls.append((url, root)))
    result = runner.invoke(app, ["eval", "prepare"])
    assert result.exit_code == 0
    assert "Evaluation database ready." in result.stdout
    assert calls == [(settings.eval_database_url, main.REPO_ROOT)]

    def fail(url: str, root: Path) -> None:
        raise DbmateError(["dbmate failed (exit 1); see its output above"], "Error: boom")

    monkeypatch.setattr(main, "prepare_eval_db", fail)
    result = runner.invoke(app, ["eval", "prepare"])
    assert result.exit_code == 1
    assert "Error: boom" in result.stderr
    assert "dbmate failed" in result.stderr


def test_prepare_refuses_dev_url(
    monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings]
) -> None:
    dev = make_settings().database_url
    respelled = dev.replace("127.0.0.1", "localhost") if "127.0.0.1" in dev else dev
    built = make_settings(SB_EVAL_DATABASE_URL=respelled)
    monkeypatch.setattr(main, "get_settings", lambda: built)
    monkeypatch.setattr(main, "prepare_eval_db", lambda url, root: pytest.fail("must not run"))
    result = runner.invoke(app, ["eval", "prepare"])
    assert result.exit_code == 1
    assert "must not be the dev or test database" in result.stderr


def test_suggest_prints_starter_yaml(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    async def paths(settings: Settings, n: int) -> list[str]:
        return ["Projects/NAS.md", "Inbox/idea.md", "Zażółć.md"][:n]

    monkeypatch.setattr(main, "_suggest_paths", paths)
    result = runner.invoke(app, ["eval", "suggest", "--n", "3"])
    assert result.exit_code == 0, result.output
    data = yaml.safe_load(result.stdout)
    assert data["version"] == 1
    assert [q["id"] for q in data["queries"]] == ["q01", "q02", "q03"]
    assert all(q["q"] == "" for q in data["queries"])
    assert data["queries"][0] == {
        "id": "q01",
        "q": "",
        "lang": "pl",
        "kind": "topic",
        "targets": ["Projects/NAS.md"],
    }
    assert "Zażółć.md" in result.stdout  # allow_unicode


def _write(path: Path, body: str) -> Path:
    path.write_text("version: 1\nqueries:\n" + body, encoding="utf-8")
    return path


def test_check_empty_q_exits_1(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, tmp_path: Path
) -> None:
    async def live(settings: Settings) -> set[str]:
        return {"Projects/NAS.md"}

    monkeypatch.setattr(main, "_dev_live_paths", live)
    queries = _write(
        tmp_path / "q.yaml",
        "  - {id: q01, q: '', lang: pl, kind: topic, targets: [Projects/NAS.md]}\n",
    )
    result = runner.invoke(app, ["eval", "check", "--queries", str(queries)])
    assert result.exit_code == 1
    assert "q01" in result.stderr and "write a question" in result.stderr


def test_check_reports_counts_and_missing_targets(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, tmp_path: Path
) -> None:
    async def live(settings: Settings) -> set[str]:
        return {"Projects/NAS.md"}

    monkeypatch.setattr(main, "_dev_live_paths", live)
    good = _write(
        tmp_path / "good.yaml",
        "  - {id: a, q: 'secret question one', lang: pl, kind: topic, targets: [Projects/NAS.md]}\n"
        "  - {id: b, q: 'secret question two', lang: en, kind: identifier,"
        " targets: [Projects/NAS.md]}\n",
    )
    result = runner.invoke(app, ["eval", "check", "--queries", str(good)])
    assert result.exit_code == 0, result.output
    assert "queries: 2" in result.stdout
    assert "by lang: en=1, pl=1" in result.stdout
    assert "by kind: identifier=1, topic=1" in result.stdout
    assert "secret question" not in result.output

    bad = _write(
        tmp_path / "bad.yaml",
        "  - {id: a, q: 'secret question', lang: pl, kind: topic, targets: [Gone.md]}\n",
    )
    result = runner.invoke(app, ["eval", "check", "--queries", str(bad)])
    assert result.exit_code == 1
    assert "a: target not in the index: Gone.md" in result.stderr
    assert "secret question" not in result.output

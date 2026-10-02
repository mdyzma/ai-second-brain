import io
import stat
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from ai_second_brain.config import Settings
from ai_second_brain.eval.database import DbmateError, EvalDatabaseError
from ai_second_brain.eval.embedding import ModelEmbedError, PreflightError
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


def test_utf8_console_survives_a_cp1250_pipe() -> None:
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1250")
    main.utf8_stream(stream)
    print("→ zażółć", file=stream)
    stream.flush()
    assert raw.getvalue().decode("utf-8").strip() == "→ zażółć"
    main.utf8_stream(object())  # streams without reconfigure() are left alone


def test_suggest_out_writes_utf8_and_refuses_overwrite(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, tmp_path: Path
) -> None:
    async def paths(settings: Settings, n: int) -> list[str]:
        return ["Projekty/Zażółć gęślą.md"]

    monkeypatch.setattr(main, "_suggest_paths", paths)
    target = tmp_path / "eval" / "queries.yaml"
    result = runner.invoke(app, ["eval", "suggest", "--out", str(target)])
    assert result.exit_code == 0, result.output
    data = yaml.safe_load(target.read_bytes().decode("utf-8"))
    assert data["queries"][0]["targets"] == ["Projekty/Zażółć gęślą.md"]
    assert "Zażółć" not in result.stdout  # written to the file, not printed

    target.write_text("keep me", encoding="utf-8")
    result = runner.invoke(app, ["eval", "suggest", "--out", str(target)])
    assert result.exit_code == 1
    assert "already exists" in result.stderr
    assert target.read_text(encoding="utf-8") == "keep me"


def test_suggest_out_expands_home(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, tmp_path: Path
) -> None:
    async def paths(settings: Settings, n: int) -> list[str]:
        return ["a.md"]

    monkeypatch.setattr(main, "_suggest_paths", paths)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    result = runner.invoke(app, ["eval", "suggest", "--out", "~/q.yaml"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "q.yaml").is_file()


def test_check_reports_loader_and_target_errors_together(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, tmp_path: Path
) -> None:
    async def live(settings: Settings) -> set[str]:
        return {"Projects/NAS.md"}

    monkeypatch.setattr(main, "_dev_live_paths", live)
    queries = _write(
        tmp_path / "q.yaml",
        "  - {id: empty, q: '', lang: pl, kind: topic, targets: [Projects/NAS.md]}\n"
        "  - {id: gone, q: 'secret text', lang: pl, kind: topic, targets: [Gone.md]}\n",
    )
    result = runner.invoke(app, ["eval", "check", "--queries", str(queries)])
    assert result.exit_code == 1
    assert "empty: q must be" in result.stderr
    assert "gone: target not in the index: Gone.md" in result.stderr
    assert "secret text" not in result.output


def test_run_falls_back_to_temp_when_report_dir_fails(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, tmp_path: Path
) -> None:
    monkeypatch.setattr(main, "run_eval", _fake_run(_result()))
    real = main.write_report
    fallback_root = tmp_path / "tmp"
    fallback_root.mkdir()
    monkeypatch.setattr(main.tempfile, "gettempdir", lambda: str(fallback_root))

    def flaky(result: Any, out_dir: Path, now: Any) -> Path:
        if out_dir == settings.eval_report_dir:
            raise PermissionError("denied")
        return real(result, out_dir, now)

    monkeypatch.setattr(main, "write_report", flaky)
    result = runner.invoke(app, ["eval", "run"])
    assert result.exit_code == 0, result.output
    [folder] = list(fallback_root.iterdir())
    assert folder.name.startswith("sb-eval-")
    [run_folder] = list(folder.iterdir())
    assert (run_folder / "report.md").is_file()
    assert "could not write" in result.stderr.lower()
    assert str(run_folder) in result.stdout


def test_run_exits_2_when_fallback_also_fails(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    monkeypatch.setattr(main, "run_eval", _fake_run(_result()))

    def broken(result: Any, out_dir: Path, now: Any) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr(main, "write_report", broken)
    result = runner.invoke(app, ["eval", "run"])
    assert result.exit_code == 2
    assert "OSError" in result.stderr


def _recording_run(calls: list[list[str]]) -> Callable[..., Any]:
    async def fake(*args: Any, **kwargs: Any) -> Any:
        calls.append(list(kwargs["models"]))
        return _result()

    return fake


def test_models_option_relabels_the_incumbent_like_the_default(
    monkeypatch: pytest.MonkeyPatch,
    make_settings: Callable[..., Settings],
    tmp_path: Path,
) -> None:
    built = make_settings(eval_dir=tmp_path / "reports", embed_model="bge-m3:567m")
    monkeypatch.setattr(main, "get_settings", lambda: built)
    calls: list[list[str]] = []
    monkeypatch.setattr(main, "run_eval", _recording_run(calls))
    result = runner.invoke(app, ["eval", "run", "--models", " bge-m3 , granite-embedding:278m"])
    assert result.exit_code == 0, result.output
    assert calls == [["bge-m3:567m", "granite-embedding:278m"]]

    result = runner.invoke(app, ["eval", "run"])
    assert result.exit_code == 0, result.output
    assert calls[1][0] == "bge-m3:567m"  # the same helper as SB_EVAL_MODELS


def test_models_option_refuses_cloud_tags_up_front(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(main, "run_eval", _recording_run(calls))
    result = runner.invoke(app, ["eval", "run", "--models", "bge-m3,big:cloud"])
    assert result.exit_code == 1
    assert "big:cloud" in result.stderr and "hosted" in result.stderr
    assert calls == []


def test_models_option_refuses_duplicates(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(main, "run_eval", _recording_run(calls))
    result = runner.invoke(app, ["eval", "run", "--models", "bge-m3,granite-embedding,bge-m3"])
    assert result.exit_code == 1
    assert "duplicate model bge-m3" in result.stderr
    assert calls == []


def test_embed_failure_names_code_and_model_and_resume(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    error = ModelEmbedError("embed_unreachable", "granite-embedding:278m")
    monkeypatch.setattr(main, "run_eval", _fake_run(error))
    result = runner.invoke(app, ["eval", "run"])
    assert result.exit_code == 2
    assert (
        "Embedding failed (embed_unreachable) for granite-embedding:278m."
        " Cached vectors are kept: run again to resume." in result.stderr
    )


@pytest.mark.parametrize(
    ("which", "message"),
    [
        ("dev", "Could not reach the dev database (DATABASE_URL)."),
        ("eval", "Could not reach the evaluation database (SB_EVAL_DATABASE_URL)."),
    ],
)
def test_unreachable_database_is_named(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, which: Any, message: str
) -> None:
    monkeypatch.setattr(main, "run_eval", _fake_run(EvalDatabaseError(which)))
    result = runner.invoke(app, ["eval", "run"])
    assert result.exit_code == 2
    assert message in result.stderr
    assert "postgres://" not in result.output


def test_unprepared_scratch_database_exits_1_with_hint(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    error = EvalConfigError(["the evaluation database does not exist: run just eval-prepare"])
    monkeypatch.setattr(main, "run_eval", _fake_run(error))
    result = runner.invoke(app, ["eval", "run"])
    assert result.exit_code == 1
    assert "run just eval-prepare" in result.stderr


def test_ctrl_c_exits_130_with_resume_hint(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    monkeypatch.setattr(main, "run_eval", _fake_run(KeyboardInterrupt()))
    result = runner.invoke(app, ["eval", "run"])
    assert result.exit_code == 130
    assert "Interrupted. Cached vectors are kept: run again to resume." in result.stderr
    assert not settings.eval_report_dir.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_fallback_report_folder_is_owner_only(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, tmp_path: Path
) -> None:
    monkeypatch.setattr(main, "run_eval", _fake_run(_result()))
    real = main.write_report
    fallback_root = tmp_path / "tmp"
    fallback_root.mkdir()
    monkeypatch.setattr(main.tempfile, "gettempdir", lambda: str(fallback_root))

    def flaky(result: Any, out_dir: Path, now: Any) -> Path:
        if out_dir == settings.eval_report_dir:
            raise PermissionError("denied")
        return real(result, out_dir, now)

    monkeypatch.setattr(main, "write_report", flaky)
    result = runner.invoke(app, ["eval", "run"])
    assert result.exit_code == 0, result.output
    [folder] = list(fallback_root.iterdir())
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700


def test_fallback_uses_a_fresh_mkdtemp_folder(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, tmp_path: Path
) -> None:
    monkeypatch.setattr(main, "run_eval", _fake_run(_result()))
    monkeypatch.setattr(main.tempfile, "gettempdir", lambda: str(tmp_path))
    prefixes: list[str] = []
    real_mkdtemp = main.tempfile.mkdtemp

    def mkdtemp(prefix: str, dir: str) -> str:  # noqa: A002 - mirrors tempfile.mkdtemp
        prefixes.append(prefix)
        return real_mkdtemp(prefix=prefix, dir=dir)

    monkeypatch.setattr(main.tempfile, "mkdtemp", mkdtemp)
    real = main.write_report

    def flaky(result: Any, out_dir: Path, now: Any) -> Path:
        if out_dir == settings.eval_report_dir:
            raise PermissionError("denied")
        return real(result, out_dir, now)

    monkeypatch.setattr(main, "write_report", flaky)
    assert runner.invoke(app, ["eval", "run"]).exit_code == 0
    assert runner.invoke(app, ["eval", "run"]).exit_code == 0
    assert prefixes == ["sb-eval-", "sb-eval-"]
    assert len([p for p in tmp_path.iterdir() if p.name.startswith("sb-eval-")]) == 2

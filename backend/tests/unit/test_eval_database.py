import subprocess
from pathlib import Path
from typing import Any

import pytest

from ai_second_brain.eval import database
from ai_second_brain.eval.queries import EvalConfigError


def test_dbmate_base_prefers_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DBMATE", "dbmate --no-dump-schema")
    assert database.dbmate_base(tmp_path) == ["dbmate", "--no-dump-schema"]


def test_dbmate_base_resolves_pnpm(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("DBMATE", raising=False)
    monkeypatch.setattr(database.shutil, "which", lambda name: f"C:/bin/{name}.cmd")
    assert database.dbmate_base(tmp_path) == [
        "C:/bin/pnpm.cmd",
        "--dir",
        str(tmp_path),
        "exec",
        "dbmate",
    ]


def test_dbmate_base_without_pnpm(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("DBMATE", raising=False)
    monkeypatch.setattr(database.shutil, "which", lambda name: None)
    with pytest.raises(EvalConfigError):
        database.dbmate_base(tmp_path)


def test_prepare_runs_two_migrations(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []
    options: list[dict[str, Any]] = []

    class Done:
        returncode = 0

    def run(cmd: list[str], **kw: Any) -> Done:
        calls.append(cmd)
        options.append(kw)
        return Done()

    monkeypatch.setenv("DBMATE", "dbmate")
    monkeypatch.setattr(database.subprocess, "run", run)
    database.prepare("postgres://u@h/x_eval", tmp_path)
    assert len(calls) == 2
    assert "--url" in calls[0] and str(tmp_path / "db" / "migrations") in calls[0]
    assert str(tmp_path / "db" / "eval" / "migrations") in calls[1]
    assert calls[1][calls[1].index("--migrations-table") + 1] == "schema_migrations_eval"
    assert "--migrations-table" not in calls[0]
    assert all(not kw.get("shell") and kw.get("timeout") for kw in options)


def test_prepare_failure_keeps_output_on_the_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class Failed:
        returncode = 3
        stdout = "partial\n"
        stderr = "Error: migration failed\n"

    monkeypatch.setenv("DBMATE", "dbmate")
    monkeypatch.setattr(database.subprocess, "run", lambda cmd, **kw: Failed())
    with pytest.raises(database.DbmateError) as caught:
        database.prepare("postgres://u:secret@h/x_eval", tmp_path)
    assert isinstance(caught.value, EvalConfigError)
    assert "migration failed" in caught.value.output
    assert "partial" in caught.value.output
    assert all("secret" not in e for e in caught.value.errors)


def test_prepare_missing_binary_is_a_config_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def run(cmd: list[str], **kw: Any) -> None:
        raise FileNotFoundError(cmd[0])

    monkeypatch.setenv("DBMATE", "no-such-dbmate")
    monkeypatch.setattr(database.subprocess, "run", run)
    with pytest.raises(EvalConfigError):
        database.prepare("postgres://u@h/x_eval", tmp_path)


def test_prepare_timeout_is_a_config_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def run(cmd: list[str], **kw: Any) -> None:
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])

    monkeypatch.setenv("DBMATE", "dbmate")
    monkeypatch.setattr(database.subprocess, "run", run)
    with pytest.raises(EvalConfigError):
        database.prepare("postgres://u@h/x_eval", tmp_path)

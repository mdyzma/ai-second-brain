import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from ai_second_brain.auth.passwords import verify_password
from ai_second_brain.config import Settings
from ai_second_brain.interfaces.cli import main
from ai_second_brain.interfaces.cli.main import app

runner = CliRunner()


def test_openapi_writes_file_with_lf_and_sorted_keys(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "openapi.json"
    result = runner.invoke(app, ["openapi", "--output", str(target)])
    assert result.exit_code == 0, result.output
    raw = target.read_bytes()
    assert b"\r\n" not in raw
    schema = json.loads(raw)
    operation_ids = {op["operationId"] for p in schema["paths"].values() for op in p.values()}
    assert operation_ids >= {
        "health",
        "ready",
        "login",
        "logout",
        "me",
        "chatStatus",
        "createSession",
        "listSessions",
        "getSession",
        "deleteSession",
        "askTurn",
    }


def test_openapi_is_deterministic(tmp_path: Path) -> None:
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    runner.invoke(app, ["openapi", "--output", str(first)])
    runner.invoke(app, ["openapi", "--output", str(second)])
    assert first.read_bytes() == second.read_bytes()


def test_openapi_to_stdout() -> None:
    result = runner.invoke(app, ["openapi"])
    assert result.exit_code == 0
    assert json.loads(result.output)["info"]["title"] == "Second Brain API"


def test_hash_password_prints_single_quoted_env_line() -> None:
    password = "zażółć gęślą jaźń 🔑 "
    result = runner.invoke(app, ["hash-password"], input=f"{password}\n{password}\n")
    assert result.exit_code == 0, result.output
    line = result.output.strip().splitlines()[-1]
    assert line.startswith("SB_OWNER_PASSWORD_HASH='$argon2id$")
    assert line.endswith("'")
    assert verify_password(line.split("=", 1)[1].strip("'"), password)


def test_hash_password_rejects_mismatch() -> None:
    result = runner.invoke(app, ["hash-password"], input="one\ntwo\none\none\n")
    assert "Error: The two entered values do not match." in result.output


def test_serve_configures_app_logger_at_info(
    monkeypatch: pytest.MonkeyPatch, make_settings: Any
) -> None:
    captured: dict[str, Any] = {}
    settings: Settings = make_settings()
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    monkeypatch.setattr(main.uvicorn, "run", lambda *args, **kwargs: captured.update(kwargs))
    result = runner.invoke(app, ["serve"])
    assert result.exit_code == 0, result.output
    log_config = captured["log_config"]
    app_logger = log_config["loggers"]["ai_second_brain"]
    assert app_logger["level"] == "INFO"
    assert app_logger["handlers"] == ["default"]
    assert app_logger["propagate"] is False
    assert "default" in log_config["handlers"]  # uvicorn's own handler is kept

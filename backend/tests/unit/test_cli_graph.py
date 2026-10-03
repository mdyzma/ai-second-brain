from collections.abc import Callable
from typing import Any, Literal

import pytest
from typer.testing import CliRunner

from ai_second_brain.config import OllamaEndpointConfig, Settings
from ai_second_brain.interfaces.cli import main
from ai_second_brain.interfaces.cli.main import app

runner = CliRunner()


def with_model(make_settings: Callable[..., Settings]) -> Settings:
    endpoint = OllamaEndpointConfig(label="t", url="http://127.0.0.1:11434", model="qwen3:8b")
    return make_settings(ollama_endpoints=[endpoint])


def test_extract_prints_queued_count(
    monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings]
) -> None:
    scopes: list[str] = []

    async def fake(settings: Settings, scope: Literal["new", "failed"]) -> int:
        scopes.append(scope)
        return 7

    monkeypatch.setattr(main, "get_settings", lambda: with_model(make_settings))
    monkeypatch.setattr(main, "_graph_extract", fake)
    result = runner.invoke(app, ["graph", "extract"])
    assert result.exit_code == 0
    assert "Queued 7 notes for extraction." in result.output
    assert runner.invoke(app, ["graph", "extract", "--failed"]).exit_code == 0
    assert scopes == ["new", "failed"]


def test_extract_without_model_exits_1(
    monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings]
) -> None:
    monkeypatch.setattr(main, "get_settings", lambda: make_settings())
    result = runner.invoke(app, ["graph", "extract"])
    assert result.exit_code == 1
    assert "No local chat model is configured for extraction (SB_EXTRACT_MODEL)." in result.output


def test_status_prints_aligned_lines(
    monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings]
) -> None:
    async def fake(settings: Settings) -> list[tuple[str, Any]]:
        return [("model", "qwen3:8b"), ("revisions.total", 3), ("entities.tool.accepted", 1)]

    monkeypatch.setattr(main, "get_settings", lambda: make_settings())
    monkeypatch.setattr(main, "_graph_status", fake)
    result = runner.invoke(app, ["graph", "status"])
    assert result.exit_code == 0
    assert result.output.splitlines() == [
        "model:                  qwen3:8b",
        "revisions.total:        3",
        "entities.tool.accepted: 1",
    ]

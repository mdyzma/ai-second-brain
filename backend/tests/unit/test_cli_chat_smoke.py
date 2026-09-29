from collections.abc import Callable

import pytest
from typer.testing import CliRunner

from ai_second_brain.config import Settings
from ai_second_brain.interfaces.cli import main
from ai_second_brain.interfaces.cli.main import app

from ..fakes.ollama import FakeOllama
from ..fakes.server import closed_port_url

runner = CliRunner()


def use_settings(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    monkeypatch.setattr(main, "get_settings", lambda: settings)


def test_smoke_reports_endpoints_and_answer(
    monkeypatch: pytest.MonkeyPatch,
    make_settings: Callable[..., Settings],
    make_fake_ollama: Callable[[], FakeOllama],
) -> None:
    fake = make_fake_ollama()
    fake.behaviour.chunks = ["ready"]
    endpoints = [
        {"label": "down", "url": closed_port_url(), "model": "m1"},
        {"label": "cpu", "url": fake.url, "model": "fake-model", "degraded": True},
    ]
    use_settings(monkeypatch, make_settings(ollama_endpoints=endpoints))
    result = runner.invoke(app, ["chat-smoke"])
    assert result.exit_code == 0, result.output
    assert "down" in result.output and "UNREACHABLE" in result.output
    assert "cpu" in result.output and "reachable (degraded)" in result.output
    assert "Answered by cpu (fake-model)" in result.output
    assert "Answer: ready" in result.output
    [request] = fake.chat_requests()
    assert "Reply with the single word: ready" in request.body["messages"][-1]["content"]


def test_smoke_fails_without_reachable_model(
    monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings]
) -> None:
    endpoints = [{"label": "down", "url": closed_port_url(), "model": "m1"}]
    use_settings(monkeypatch, make_settings(ollama_endpoints=endpoints))
    result = runner.invoke(app, ["chat-smoke"])
    assert result.exit_code == 1
    assert "no_local_model" in result.output


def test_smoke_explains_missing_configuration(
    monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings]
) -> None:
    use_settings(monkeypatch, make_settings())
    result = runner.invoke(app, ["chat-smoke"])
    assert result.exit_code == 1
    assert "SB_OLLAMA_ENDPOINTS" in result.output

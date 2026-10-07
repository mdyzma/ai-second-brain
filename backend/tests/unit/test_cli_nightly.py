from collections.abc import Callable
from typing import Any

import pytest
from typer.testing import CliRunner

from ai_second_brain.config import Settings
from ai_second_brain.interfaces.cli import main
from ai_second_brain.interfaces.cli.main import app

runner = CliRunner()


def run_row(**over: Any) -> dict[str, Any]:
    return {
        "status": "complete", "queued_new": 5, "queued_failed": 2, "done": 7, "error": None,
        "timed_out": False, "unavailable": False, **over,
    }  # fmt: skip


def body(run: dict[str, Any], failed: int = 1, remaining: int = 18) -> dict[str, Any]:
    return {"run": run, "failed": {"count": failed, "items": [{"path": "Secret/Name.md"}]},
            "review": {"remaining": remaining}}  # fmt: skip


@pytest.fixture(autouse=True)
def settings(monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings]) -> None:
    monkeypatch.setattr(main, "get_settings", lambda: make_settings())


def patch_run(monkeypatch: pytest.MonkeyPatch, outcome: str, run: dict[str, Any] | None) -> None:
    async def fake(settings: Settings) -> tuple[str, dict[str, Any] | None]:
        return outcome, run

    monkeypatch.setattr(main, "_nightly_run", fake)


def test_run_prints_queued_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_run(monkeypatch, "started", run_row())
    result = runner.invoke(app, ["nightly", "run"])
    assert result.exit_code == 0
    assert "Started a nightly run: queued 5 new and 2 failed notes." in result.output


def test_run_busy_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_run(monkeypatch, "busy", None)
    result = runner.invoke(app, ["nightly", "run"])
    assert result.exit_code == 1 and "A run is already in progress." in result.stderr


def test_run_failed_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_run(monkeypatch, "failed", run_row(status="failed", error="db_error"))
    result = runner.invoke(app, ["nightly", "run"])
    assert result.exit_code == 1 and "Nightly run failed: db_error" in result.stderr


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (None, "No nightly run yet."),
        (body(run_row()), "Last night: 7 notes read, 1 failed, 18 to review."),
        (body(run_row(status="running", done=3)), "Reading notes: 3 of 7."),
        (
            body(run_row(unavailable=True)),
            "Extraction is off: no Ollama endpoint is configured (`SB_OLLAMA_ENDPOINTS`).",
        ),
        (
            body(run_row(status="failed", error="db_error")),
            "Last night's run failed to start (db_error). It will try again at the next check.",
        ),
    ],
)
def test_status_summary(
    monkeypatch: pytest.MonkeyPatch, data: dict[str, Any] | None, expected: str
) -> None:
    async def fake(settings: Settings) -> dict[str, Any] | None:
        return data

    monkeypatch.setattr(main, "_nightly_status", fake)
    result = runner.invoke(app, ["nightly", "status"])
    assert result.exit_code == 0 and result.output.strip() == expected
    assert "Secret" not in result.output


def test_status_timed_out_adds_the_stop_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(settings: Settings) -> dict[str, Any] | None:
        return body(run_row(timed_out=True))

    monkeypatch.setattr(main, "_nightly_status", fake)
    out = runner.invoke(app, ["nightly", "status"]).output
    assert "Stopped waiting after 8 hours. Remaining notes will finish in the background." in out

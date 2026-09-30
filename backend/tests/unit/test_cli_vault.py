from collections.abc import Callable

import pytest
from typer.testing import CliRunner

from ai_second_brain.config import Settings
from ai_second_brain.interfaces.cli import main
from ai_second_brain.interfaces.cli.main import app

runner = CliRunner()


def test_vault_commands_explain_missing_vault(
    monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings]
) -> None:
    monkeypatch.setattr(main, "get_settings", lambda: make_settings())
    result = runner.invoke(app, ["vault", "reconcile"])
    assert result.exit_code == 1
    assert "SB_VAULT_PATH" in result.output

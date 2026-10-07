from collections.abc import Callable
from datetime import time

import pytest
from pydantic import ValidationError

from ai_second_brain.config import Settings


@pytest.fixture
def make(
    monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings]
) -> Callable[..., Settings]:
    # Same base as the other config tests (make_settings); SB_* names go in via the environment.
    def _make(**env: str) -> Settings:
        for name in (
            "SB_NIGHTLY_ENABLED",
            "SB_NIGHTLY_AT",
            "SB_TIMEZONE",
            "SB_NIGHTLY_MAX_NOTES",
            "SB_NIGHTLY_MAX_HOURS",
        ):
            monkeypatch.delenv(name, raising=False)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        return make_settings()

    return _make


def test_defaults(make: Callable[..., Settings]) -> None:
    s = make()
    assert s.nightly_enabled is True
    assert s.nightly_time == time(2, 0)
    assert s.nightly_max_notes == 500 and s.nightly_max_hours == 8


def test_valid_values(make: Callable[..., Settings]) -> None:
    s = make(SB_NIGHTLY_AT="23:45", SB_TIMEZONE="Europe/Warsaw", SB_NIGHTLY_ENABLED="false")
    assert s.nightly_time == time(23, 45) and s.nightly_enabled is False
    assert str(s.nightly_zone) == "Europe/Warsaw"


@pytest.mark.parametrize(
    "env",
    [
        {"SB_NIGHTLY_AT": "25:00"},
        {"SB_TIMEZONE": "Mars/Base"},
        {"SB_NIGHTLY_MAX_NOTES": "0"},
        {"SB_NIGHTLY_MAX_HOURS": "49"},
    ],
)
def test_invalid_values(make: Callable[..., Settings], env: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        make(**env)

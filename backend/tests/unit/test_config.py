from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_second_brain.config import ENV_FILE, REPO_ROOT, Settings

from ..conftest import TEST_HASH

ENV_VARS = [
    "DATABASE_URL",
    "TEST_DATABASE_URL",
    "SB_OWNER_PASSWORD_HASH",
    "SB_SESSION_TTL_DAYS",
    "SB_COOKIE_SECURE",
    "SB_ALLOWED_ORIGINS",
    "SB_API_PORT",
    "SB_ENV",
]


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_env_file_is_repository_root_env() -> None:
    assert REPO_ROOT / ".env" == ENV_FILE
    assert (REPO_ROOT / "backend" / "pyproject.toml").is_file()


def test_defaults(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings()
    assert settings.session_ttl_days == 14
    assert settings.cookie_secure is False
    assert settings.env == "dev"
    assert settings.api_port == 8000


@pytest.mark.parametrize("bad", ["", "plain-text", "=19=65536,t=3,p=4"])
def test_rejects_missing_or_corrupted_hash(
    make_settings: Callable[..., Settings], bad: str
) -> None:
    with pytest.raises(ValidationError) as excinfo:
        make_settings(owner_password_hash=bad)
    message = str(excinfo.value)
    assert "just hash-password" in message
    assert "single quotes" in message


@pytest.mark.usefixtures("clean_env")
def test_missing_hash_is_rejected_even_when_not_passed() -> None:
    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None, DATABASE_URL="postgres://u:p@localhost/db")  # pyright: ignore[reportCallIssue]
    assert "just hash-password" in str(excinfo.value)


def test_rejects_unknown_env(make_settings: Callable[..., Settings]) -> None:
    with pytest.raises(ValidationError):
        make_settings(env="staging")


def test_allowed_origin_set_trims_and_drops_trailing_slash(
    make_settings: Callable[..., Settings],
) -> None:
    settings = make_settings(allowed_origins=" http://localhost:5173/ ,http://brain.lan ,, ")
    assert settings.allowed_origin_set == frozenset({"http://localhost:5173", "http://brain.lan"})


@pytest.mark.usefixtures("clean_env")
def test_reads_single_quoted_hash_from_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DATABASE_URL=postgres://u:p@localhost:5432/db\n"
        f"SB_OWNER_PASSWORD_HASH='{TEST_HASH}'\n"
        "SB_ENV=prod\n",
        encoding="utf-8",
    )
    settings = Settings(_env_file=env_file)  # pyright: ignore[reportCallIssue]
    assert settings.owner_password_hash == TEST_HASH
    assert settings.database_url == "postgres://u:p@localhost:5432/db"
    assert settings.env == "prod"

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from ai_second_brain.config import Settings

from ..conftest import TEST_HASH


def make(**values: Any) -> Settings:
    base: dict[str, Any] = {
        "DATABASE_URL": "postgres://x@127.0.0.1:1/x",
        "owner_password_hash": TEST_HASH,
    }
    return Settings(_env_file=None, **(base | values))  # pyright: ignore[reportCallIssue]


def test_defaults(tmp_path: Path) -> None:
    settings = make(vault_path=str(tmp_path / "My Vault"))
    assert settings.capture_dir == tmp_path / "My Vault" / "Inbox"
    assert settings.obsidian_vault_name == "My Vault"
    assert settings.chat_num_ctx == 8192
    assert settings.retrieval_min_similarity == 0.45


def test_no_vault_means_no_capture_dir() -> None:
    settings = make()
    assert settings.capture_dir is None and settings.obsidian_vault_name == ""


@pytest.mark.parametrize(
    "bad", ["../outside", "/abs", "C:\\abs", "a/../../b", ".obsidian/inbox", ""]
)
def test_capture_dir_must_stay_inside_and_not_excluded(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValidationError):
        make(vault_path=str(tmp_path), SB_CAPTURE_DIR=bad)


def test_capture_dir_nested_ok(tmp_path: Path) -> None:
    assert make(vault_path=str(tmp_path), SB_CAPTURE_DIR="00 Inbox/app").capture_dir == (
        tmp_path / "00 Inbox" / "app"
    )


def test_capture_dir_must_not_be_an_existing_file(tmp_path: Path) -> None:
    (tmp_path / "Inbox").write_text("not a folder", encoding="utf-8")
    with pytest.raises(ValidationError) as error:
        make(vault_path=str(tmp_path), SB_CAPTURE_DIR="Inbox")
    assert "must not be an existing file" in str(error.value)


def test_capture_dir_file_check_needs_a_vault(tmp_path: Path) -> None:
    assert make(SB_CAPTURE_DIR="Inbox").capture_dir is None


def test_obsidian_vault_override(tmp_path: Path) -> None:
    assert make(vault_path=str(tmp_path), obsidian_vault="Brain").obsidian_vault_name == "Brain"


@pytest.mark.parametrize(
    ("field", "value"),
    [("chat_num_ctx", 1024), ("chat_num_ctx", 200000), ("retrieval_min_similarity", 1.5)],
)
def test_ranges(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        make(**{field: value})

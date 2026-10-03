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


def test_extract_model_defaults_to_first_endpoint() -> None:
    s = make(
        ollama_endpoints=[{"label": "ws", "url": "http://127.0.0.1:11434", "model": "qwen3:14b"}]
    )
    assert s.extract_model_name == "qwen3:14b"
    assert make().extract_model_name is None
    assert make(SB_EXTRACT_MODEL="llama3.1:8b").extract_model_name == "llama3.1:8b"


def test_extract_defaults() -> None:
    s = make()
    assert (s.extract_auto_accept, s.entity_match_similarity, s.extract_window_chars) == (
        0.8,
        0.90,
        6000,
    )


def test_extract_cloud_model_refused() -> None:
    with pytest.raises(ValidationError):
        make(SB_EXTRACT_MODEL="gpt-oss:120b-cloud")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("extract_auto_accept", 1.5),
        ("entity_match_similarity", -0.1),
        ("extract_window_chars", 1000),
        ("extract_window_chars", 40000),
    ],
)
def test_ranges(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        make(**{field: value})

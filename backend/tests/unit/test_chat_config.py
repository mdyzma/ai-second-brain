from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_second_brain.config import OllamaEndpointConfig, Settings

from ..conftest import TEST_HASH, UNUSED_DB

WORKSTATION = {"label": "workstation", "url": "http://192.168.88.10:11434/", "model": "qwen3:32b"}


def test_chat_defaults(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings()
    assert settings.ollama_endpoints == []
    assert settings.cloud_available is False
    assert settings.anthropic_model == "claude-sonnet-5-5"
    assert settings.anthropic_base_url == "https://api.anthropic.com"
    assert settings.chat_max_tokens == 2048
    assert settings.chat_status_ttl_seconds == 10.0


def test_endpoints_keep_order_and_strip_trailing_slash(
    make_settings: Callable[..., Settings],
) -> None:
    proxmox = {
        "label": "proxmox",
        "url": "https://ollama.lan",
        "model": "qwen3:8b",
        "degraded": True,
    }
    settings = make_settings(ollama_endpoints=[WORKSTATION, proxmox])
    assert [e.label for e in settings.ollama_endpoints] == ["workstation", "proxmox"]
    assert settings.ollama_endpoints[0].url == "http://192.168.88.10:11434"
    assert settings.ollama_endpoints[0].degraded is False
    assert settings.ollama_endpoints[1].degraded is True


@pytest.mark.parametrize(
    "url",
    [
        "ftp://192.168.88.10:11434",
        "http://",
        "192.168.88.10:11434",
        "http://user:pw@192.168.88.10:11434",
        "http://192.168.88.10:11434/?x=1",
        "http://192.168.88.10:11434/#frag",
        "http://192.168.88.10:11434?",
    ],
)
def test_endpoint_url_rules(url: str) -> None:
    with pytest.raises(ValidationError):
        OllamaEndpointConfig(label="ws", url=url, model="m")


@pytest.mark.parametrize("label", ["", "Work Station", "UPPER", "x" * 33, "under_score"])
def test_endpoint_label_rules(label: str) -> None:
    with pytest.raises(ValidationError):
        OllamaEndpointConfig(label=label, url="http://127.0.0.1:11434", model="m")


def test_endpoint_model_required() -> None:
    with pytest.raises(ValidationError):
        OllamaEndpointConfig(label="ws", url="http://127.0.0.1:11434", model="")


def test_duplicate_labels_rejected(make_settings: Callable[..., Settings]) -> None:
    with pytest.raises(ValidationError, match="unique"):
        make_settings(ollama_endpoints=[WORKSTATION, WORKSTATION])


def test_errors_never_echo_the_value(make_settings: Callable[..., Settings]) -> None:
    bad = {**WORKSTATION, "url": "http://user:hunter2-secret@192.168.88.10:11434"}
    with pytest.raises(ValidationError) as error:
        make_settings(ollama_endpoints=[bad])
    assert "hunter2-secret" not in str(error.value)


@pytest.mark.parametrize("value", [0, 63, 32001])
def test_max_tokens_bounds(make_settings: Callable[..., Settings], value: int) -> None:
    with pytest.raises(ValidationError):
        make_settings(chat_max_tokens=value)


def test_cloud_available_needs_a_non_blank_key(make_settings: Callable[..., Settings]) -> None:
    assert make_settings(anthropic_api_key="   ").cloud_available is False
    settings = make_settings(anthropic_api_key="sk-test-key")
    assert settings.cloud_available is True
    assert "sk-test-key" not in repr(settings)


def test_loads_from_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SB_OLLAMA_ENDPOINTS="
        '\'[{"label":"ws","url":"http://127.0.0.1:11434","model":"m"}]\'\n'
        "SB_ANTHROPIC_API_KEY=sk-from-file\n",
        encoding="utf-8",
    )
    settings = Settings(
        _env_file=env_file,  # pyright: ignore[reportCallIssue]
        DATABASE_URL=UNUSED_DB,  # pyright: ignore[reportCallIssue]
        owner_password_hash=TEST_HASH,
    )
    assert [e.label for e in settings.ollama_endpoints] == ["ws"]
    assert settings.cloud_available is True


def test_loads_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "SB_OLLAMA_ENDPOINTS", '[{"label":"ws","url":"http://127.0.0.1:11434","model":"m"}]'
    )
    monkeypatch.setenv("SB_CHAT_MAX_TOKENS", "512")
    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        DATABASE_URL=UNUSED_DB,  # pyright: ignore[reportCallIssue]
        owner_password_hash=TEST_HASH,
    )
    assert settings.ollama_endpoints[0].model == "m"
    assert settings.chat_max_tokens == 512


def test_empty_endpoint_variable_means_no_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SB_OLLAMA_ENDPOINTS", "")
    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        DATABASE_URL=UNUSED_DB,  # pyright: ignore[reportCallIssue]
        owner_password_hash=TEST_HASH,
    )
    assert settings.ollama_endpoints == []

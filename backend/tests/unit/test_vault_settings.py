from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_second_brain.config import OllamaEndpointConfig, Settings, http_url


def test_ingest_defaults(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings()
    assert settings.vault_path is None
    assert settings.vault_excludes == (".obsidian/**", ".trash/**", "**/.git/**")
    assert settings.embed_url is None
    assert settings.embed_model == "bge-m3"
    assert settings.embed_batch == 16
    assert settings.reconcile_minutes == 15
    assert settings.max_note_bytes == 2_000_000


def test_embed_url_falls_back_to_first_chat_endpoint(
    make_settings: Callable[..., Settings],
) -> None:
    endpoints = [
        {"label": "gpu", "url": "http://10.0.0.5:11434/", "model": "m"},
        {"label": "cpu", "url": "http://10.0.0.6:11434", "model": "m"},
    ]
    assert make_settings(ollama_endpoints=endpoints).embed_url == "http://10.0.0.5:11434"
    explicit = make_settings(
        ollama_endpoints=endpoints, embed_url_override="http://10.0.0.9:11434/"
    )
    assert explicit.embed_url == "http://10.0.0.9:11434"


@pytest.mark.parametrize(
    "url", ["ftp://h", "http://", "http://u:p@h", "http://h/?x", "http://h#f", "h:11434"]
)
def test_embed_url_rules(make_settings: Callable[..., Settings], url: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(embed_url_override=url)


def test_http_url_is_shared_with_chat_endpoints() -> None:
    assert http_url(" http://h:1/ ") == "http://h:1"
    with pytest.raises(ValidationError):
        OllamaEndpointConfig(label="x", url="http://u:p@h", model="m")


def test_vault_path_must_be_absolute(
    make_settings: Callable[..., Settings], tmp_path: Path
) -> None:
    assert make_settings(vault_path=str(tmp_path)).vault_path == tmp_path
    with pytest.raises(ValidationError):
        make_settings(vault_path="relative/vault")


def test_excludes_parse_and_trim(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(vault_exclude=" Archive/** , ,*.tmp.md ")
    assert settings.vault_excludes == ("Archive/**", "*.tmp.md")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("embed_batch", 0),
        ("embed_batch", 129),
        ("reconcile_minutes", 0),
        ("reconcile_minutes", 1441),
        ("max_note_bytes", 999),
        ("max_note_bytes", 50_000_001),
        ("embed_model", ""),
    ],
)
def test_bounds(make_settings: Callable[..., Settings], field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        make_settings(**{field: value})


def test_embed_url_env_alias(
    monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings]
) -> None:
    monkeypatch.setenv("SB_EMBED_URL", "http://127.0.0.1:11434")
    assert make_settings().embed_url == "http://127.0.0.1:11434"


@pytest.mark.parametrize("model", ["kimi-k2.6:cloud", "qwen3-coder:480b-cloud", "GLM-5:CLOUD"])
def test_hosted_ollama_models_are_rejected(
    make_settings: Callable[..., Settings], model: str
) -> None:
    with pytest.raises(ValidationError):
        make_settings(embed_model=model)
    with pytest.raises(ValidationError):
        OllamaEndpointConfig(label="x", url="http://127.0.0.1:11434", model=model)


def test_tagged_local_models_are_fine(make_settings: Callable[..., Settings]) -> None:
    assert make_settings(embed_model="bge-m3:567m").embed_model == "bge-m3:567m"
    assert (
        OllamaEndpointConfig(label="x", url="http://127.0.0.1:11434", model="gemma4:26b").model
        == "gemma4:26b"
    )


def test_model_matches_space() -> None:
    from ai_second_brain.config import model_matches_space

    assert model_matches_space("bge-m3", "bge-m3")
    assert model_matches_space("bge-m3:567m", "bge-m3")
    assert not model_matches_space("bge-m3x", "bge-m3")
    assert not model_matches_space("nomic-embed-text", "bge-m3")

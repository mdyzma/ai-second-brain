"""Settings from the environment and the repository-root .env file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = REPO_ROOT / ".env"

HASH_HINT = (
    "Run `just hash-password` and paste the printed line into .env. "
    "Keep the single quotes: unquoted '$' characters are expanded by just's .env loader."
)


class OllamaEndpointConfig(BaseModel):
    """One Ollama endpoint on the owner's LAN. List order is preference order."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    label: str = Field(pattern=r"^[a-z0-9-]{1,32}$")
    url: str
    model: str = Field(min_length=1, max_length=200)
    degraded: bool = False

    @field_validator("url")
    @classmethod
    def _check_url(cls, value: str) -> str:
        value = value.strip()
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("must be an http:// or https:// URL with a host")
        if parts.username is not None or parts.password is not None:
            raise ValueError("must not contain a user name or password")
        if "?" in value or "#" in value:
            raise ValueError("must not contain a query string or fragment")
        return value.rstrip("/")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SB_",
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
        populate_by_name=True,
        hide_input_in_errors=True,
    )

    database_url: str = Field(validation_alias="DATABASE_URL")
    owner_password_hash: str = Field(default="", validate_default=True)
    session_ttl_days: int = Field(default=14, ge=1, le=365)
    cookie_secure: bool = False
    allowed_origins: str = "http://localhost:5173"
    api_port: int = 8000
    env: Literal["dev", "prod"] = "dev"
    ollama_endpoints: list[OllamaEndpointConfig] = Field(default_factory=list)
    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_model: str = Field(default="claude-sonnet-5-5", min_length=1)
    anthropic_base_url: str = "https://api.anthropic.com"  # pinned; tests point it at a fake
    chat_max_tokens: int = Field(default=2048, ge=64, le=32000)
    chat_status_ttl_seconds: float = Field(default=10.0, ge=0, le=300)

    @field_validator("owner_password_hash")
    @classmethod
    def _must_be_argon2(cls, value: str) -> str:
        if not value.startswith("$argon2"):
            raise ValueError(
                f"SB_OWNER_PASSWORD_HASH is missing or not an argon2 hash. {HASH_HINT}"
            )
        return value

    @field_validator("ollama_endpoints")
    @classmethod
    def _unique_labels(cls, value: list[OllamaEndpointConfig]) -> list[OllamaEndpointConfig]:
        labels = [endpoint.label for endpoint in value]
        if len(labels) != len(set(labels)):
            raise ValueError("endpoint labels must be unique")
        return value

    @property
    def cloud_available(self) -> bool:
        return bool(self.anthropic_api_key.get_secret_value().strip())

    @property
    def allowed_origin_set(self) -> frozenset[str]:
        parts = (origin.strip().rstrip("/") for origin in self.allowed_origins.split(","))
        return frozenset(origin for origin in parts if origin)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]

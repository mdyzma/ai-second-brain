"""Settings from the environment and the repository-root .env file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = REPO_ROOT / ".env"

HASH_HINT = (
    "Run `just hash-password` and paste the printed line into .env. "
    "Keep the single quotes: unquoted '$' characters are expanded by just's .env loader."
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SB_",
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    database_url: str = Field(validation_alias="DATABASE_URL")
    owner_password_hash: str = Field(default="", validate_default=True)
    session_ttl_days: int = Field(default=14, ge=1, le=365)
    cookie_secure: bool = False
    allowed_origins: str = "http://localhost:5173"
    api_port: int = 8000
    env: Literal["dev", "prod"] = "dev"

    @field_validator("owner_password_hash")
    @classmethod
    def _must_be_argon2(cls, value: str) -> str:
        if not value.startswith("$argon2"):
            raise ValueError(
                f"SB_OWNER_PASSWORD_HASH is missing or not an argon2 hash. {HASH_HINT}"
            )
        return value

    @property
    def allowed_origin_set(self) -> frozenset[str]:
        parts = (origin.strip().rstrip("/") for origin in self.allowed_origins.split(","))
        return frozenset(origin for origin in parts if origin)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]

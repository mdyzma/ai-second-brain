"""Settings from the environment and the repository-root .env file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .vault.paths import _excluded

REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = REPO_ROOT / ".env"

HASH_HINT = (
    "Run `just hash-password` and paste the printed line into .env. "
    "Keep the single quotes: unquoted '$' characters are expanded by just's .env loader."
)


def http_url(value: str) -> str:
    """Validated http(s) origin/base URL: host required, no credentials, query or fragment."""
    value = value.strip()
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("must be an http:// or https:// URL with a host")
    if parts.username is not None or parts.password is not None:
        raise ValueError("must not contain a user name or password")
    if "?" in value or "#" in value:
        raise ValueError("must not contain a query string or fragment")
    return value.rstrip("/")


HOSTED_MODEL_SUFFIXES = (":cloud", "-cloud")


def local_model_name(value: str) -> str:
    """Reject Ollama's hosted models: they forward prompts to ollama.com."""
    value = value.strip()
    if value.lower().endswith(HOSTED_MODEL_SUFFIXES):
        raise ValueError("hosted (cloud) Ollama models are not allowed; use a local model")
    return value


def model_matches_space(tag: str, space_model: str) -> bool:
    """An Ollama tag like 'bge-m3:567m' belongs to the embedding space 'bge-m3'."""
    return tag == space_model or tag.startswith(f"{space_model}:")


def eval_model_tags(raw: str, embed_model: str) -> list[str]:
    """Parse comma-separated eval tags (SB_EVAL_MODELS or --models).

    Every tag must be local; the first (the incumbent) becomes the SB_EMBED_MODEL tag when it
    names the same model; a tag listed twice is refused. Raises ValueError with a clear message.
    """
    tags: list[str] = []
    for raw_tag in raw.split(","):
        if not raw_tag.strip():
            continue
        try:
            tags.append(local_model_name(raw_tag))
        except ValueError as error:
            raise ValueError(f"{raw_tag.strip()}: {error}") from None
    if not tags:
        raise ValueError("no models to evaluate: name at least one model")
    if embed_model and model_matches_space(embed_model, tags[0]):
        tags[0] = embed_model
    seen: set[str] = set()
    for tag in tags:
        if tag in seen:
            raise ValueError(f"duplicate model {tag}")
        seen.add(tag)
    return tags


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
        return http_url(value)

    @field_validator("model")
    @classmethod
    def _local_model(cls, value: str) -> str:
        return local_model_name(value)


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

    vault_path: Path | None = None
    vault_exclude: str = ".obsidian/**,.trash/**,**/.git/**"
    embed_url_override: str = Field(default="", validation_alias="SB_EMBED_URL")
    embed_model: str = Field(default="bge-m3", min_length=1)
    embed_batch: int = Field(default=16, ge=1, le=128)
    reconcile_minutes: int = Field(default=15, ge=1, le=1440)
    max_note_bytes: int = Field(default=2_000_000, ge=1_000, le=50_000_000)
    capture_dir_name: str = Field(default="Inbox", validation_alias="SB_CAPTURE_DIR")
    obsidian_vault: str = ""
    chat_num_ctx: int = Field(default=8192, ge=2048, le=131072)
    retrieval_min_similarity: float = Field(default=0.45, ge=0.0, le=1.0)
    extract_model: str = Field(default="", validation_alias="SB_EXTRACT_MODEL")
    extract_auto_accept: float = Field(default=0.8, ge=0.0, le=1.0)
    entity_match_similarity: float = Field(default=0.90, ge=0.0, le=1.0)
    extract_window_chars: int = Field(default=6000, ge=2000, le=32000)
    eval_queries: Path = Path("~/.second-brain/eval/queries.yaml")
    eval_dir: Path = Path("~/.second-brain/eval/reports")
    eval_database_url_override: str = Field(default="", validation_alias="SB_EVAL_DATABASE_URL")
    eval_models: str = (
        "bge-m3,snowflake-arctic-embed2,granite-embedding:278m,paraphrase-multilingual"
    )

    @field_validator("eval_models")
    @classmethod
    def _eval_models_local(cls, value: str) -> str:
        if not value.replace(",", "").strip():
            raise ValueError("SB_EVAL_MODELS needs at least one model")
        return ",".join(eval_model_tags(value, ""))

    @field_validator("eval_dir")
    @classmethod
    def _eval_dir_outside_repo(cls, value: Path) -> Path:
        resolved = value.expanduser().resolve()
        if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
            raise ValueError("SB_EVAL_DIR must be outside the repository (reports name your notes)")
        return value

    @field_validator("vault_path")
    @classmethod
    def _absolute_vault(cls, value: Path | None) -> Path | None:
        if value is not None and not value.is_absolute():
            raise ValueError("SB_VAULT_PATH must be an absolute path")
        return value

    @field_validator("embed_url_override")
    @classmethod
    def _embed_url(cls, value: str) -> str:
        return http_url(value) if value.strip() else ""

    @field_validator("extract_model")
    @classmethod
    def _local_extract_model(cls, value: str) -> str:
        return local_model_name(value) if value.strip() else ""

    @field_validator("embed_model")
    @classmethod
    def _local_embed_model(cls, value: str) -> str:
        return local_model_name(value)

    @model_validator(mode="after")
    def _capture_dir_inside_vault(self) -> Settings:
        raw = self.capture_dir_name.strip()
        parts = PurePosixPath(raw.replace("\\", "/")).parts
        if (
            not raw
            or PureWindowsPath(raw).is_absolute()
            or raw.startswith(("/", "\\"))
            or ".." in parts
            or ":" in raw
        ):
            raise ValueError("SB_CAPTURE_DIR must be a relative folder inside the vault")
        rel = "/".join(parts)
        if _excluded(f"{rel}/x.md", self.vault_excludes):
            raise ValueError("SB_CAPTURE_DIR must not be excluded by SB_VAULT_EXCLUDE")
        self.capture_dir_name = rel
        if (capture_dir := self.capture_dir) is not None and capture_dir.is_file():
            raise ValueError("SB_CAPTURE_DIR must not be an existing file")
        return self

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
    def eval_queries_path(self) -> Path:
        return self.eval_queries.expanduser()

    @property
    def eval_report_dir(self) -> Path:
        return self.eval_dir.expanduser().resolve()  # the same path the repo check validated

    @property
    def eval_database_url(self) -> str:
        if self.eval_database_url_override.strip():
            return self.eval_database_url_override.strip()
        parts = urlsplit(self.database_url)
        return urlunsplit(parts._replace(path=f"{parts.path.rstrip('/')}_eval"))

    @property
    def eval_model_list(self) -> list[str]:
        return eval_model_tags(self.eval_models, self.embed_model)

    @property
    def cloud_available(self) -> bool:
        return bool(self.anthropic_api_key.get_secret_value().strip())

    @property
    def vault_excludes(self) -> tuple[str, ...]:
        return tuple(p.strip() for p in self.vault_exclude.split(",") if p.strip())

    @property
    def capture_dir(self) -> Path | None:
        if self.vault_path is None:
            return None
        return self.vault_path.joinpath(*PurePosixPath(self.capture_dir_name).parts)

    @property
    def obsidian_vault_name(self) -> str:
        if self.obsidian_vault.strip():
            return self.obsidian_vault.strip()
        return self.vault_path.name if self.vault_path is not None else ""

    @property
    def embed_url(self) -> str | None:
        if self.embed_url_override:
            return self.embed_url_override
        return self.ollama_endpoints[0].url if self.ollama_endpoints else None

    @property
    def extract_model_name(self) -> str | None:
        """The extraction model, or None (extraction disabled) with no local endpoint."""
        if not self.ollama_endpoints:
            return None
        return self.extract_model or self.ollama_endpoints[0].model

    @property
    def allowed_origin_set(self) -> frozenset[str]:
        parts = (origin.strip().rstrip("/") for origin in self.allowed_origins.split(","))
        return frozenset(origin for origin in parts if origin)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]

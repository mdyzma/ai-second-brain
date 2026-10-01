"""Chat domain types. Pydantic models double as API response schemas."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, TypedDict
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

TITLE_LENGTH = 80


def utc_now() -> datetime:
    return datetime.now(UTC)


class ChatMode(StrEnum):
    PRIVATE = "private"
    CLOUD = "cloud"


class Tier(StrEnum):
    LOCAL = "local"
    CLOUD = "cloud"


class Source(BaseModel):
    model_config = ConfigDict(frozen=True)

    n: int = Field(ge=1)
    source_id: str
    path: str
    heading: str | None = None
    score: float
    snippet: str
    obsidian_url: str | None = None


class ChatSession(BaseModel):
    id: UUID
    mode: ChatMode
    title: str | None
    created_at: datetime
    updated_at: datetime


class Turn(BaseModel):
    id: UUID
    seq: int
    question: str
    answer: str
    sources: list[Source]
    endpoint: str
    model: str
    degraded: bool
    started_at: datetime
    finished_at: datetime


@dataclass(frozen=True, slots=True)
class TurnDraft:
    question: str
    answer: str
    sources: list[Source]
    endpoint: str
    model: str
    degraded: bool
    started_at: datetime
    finished_at: datetime


class ChatMessage(TypedDict):
    role: Literal["user", "assistant"]
    content: str

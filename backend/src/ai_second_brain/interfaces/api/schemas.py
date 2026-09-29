"""Pydantic models that form the public API contract (and the generated TS client)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_second_brain.chat.models import ChatMode, ChatSession, Turn


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ReadyResponse(BaseModel):
    status: Literal["ready", "unavailable"]
    database: Literal["ok", "error"]


class ErrorResponse(BaseModel):
    detail: str


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=1024)


class MeResponse(BaseModel):
    authenticated: Literal[True]
    expires_at: datetime


MAX_QUESTION_LENGTH = 8000


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: ChatMode = ChatMode.PRIVATE


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str

    @field_validator("question")
    @classmethod
    def _trimmed_length(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= MAX_QUESTION_LENGTH:
            raise ValueError("question must be 1-8000 characters after trimming")
        return value


class SessionDetail(ChatSession):
    turns: list[Turn]


class EndpointStatusOut(BaseModel):
    label: str
    model: str
    degraded: bool
    reachable: bool


class PrivateTierStatus(BaseModel):
    available: bool
    endpoints: list[EndpointStatusOut]


class CloudTierStatus(BaseModel):
    available: bool
    model: str | None


class ChatStatusResponse(BaseModel):
    private: PrivateTierStatus
    cloud: CloudTierStatus

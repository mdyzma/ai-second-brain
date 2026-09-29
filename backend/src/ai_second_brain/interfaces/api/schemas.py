"""Pydantic models that form the public API contract (and the generated TS client)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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

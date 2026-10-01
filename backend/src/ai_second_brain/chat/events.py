"""Turn events, sent to the browser as Server-Sent Events (one JSON object per `data:`)."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, RootModel

from ai_second_brain.chat.models import Source
from ai_second_brain.chat.retrieval import RetrievalMode

PING = ": ping\n\n"


class _Event(BaseModel):
    # Responses only: mark defaulted fields (e.g. `event`) required so TS gets a real union.
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class StatusEvent(_Event):
    event: Literal["status"] = "status"
    phase: Literal["retrieving", "connecting", "generating"]
    endpoint: str | None = None
    model: str | None = None
    degraded: bool | None = None


class SourcesEvent(_Event):
    event: Literal["sources"] = "sources"
    items: list[Source]
    disabled: bool


class TokenEvent(_Event):
    event: Literal["token"] = "token"
    text: str


class ReceiptEvent(_Event):
    event: Literal["receipt"] = "receipt"
    turn_id: UUID
    seq: int
    endpoint: str
    model: str
    degraded: bool
    duration_ms: int
    retrieval: RetrievalMode = "none"


class DoneEvent(_Event):
    event: Literal["done"] = "done"


class ErrorEvent(_Event):
    event: Literal["error"] = "error"
    code: str
    component: str
    message: str


TurnEvent = Annotated[
    StatusEvent | SourcesEvent | TokenEvent | ReceiptEvent | DoneEvent | ErrorEvent,
    Field(discriminator="event"),
]


class TurnEventStream(RootModel[TurnEvent]):
    """OpenAPI description of one SSE `data:` payload."""


def encode_sse(event: TurnEvent) -> str:
    return f"event: {event.event}\ndata: {event.model_dump_json()}\n\n"

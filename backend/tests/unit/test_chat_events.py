import json
from uuid import uuid4

from ai_second_brain.chat.events import (
    ErrorEvent,
    ReceiptEvent,
    StatusEvent,
    TokenEvent,
    TurnEventStream,
    encode_sse,
)


def test_encode_sse_frames_one_event() -> None:
    frame = encode_sse(TokenEvent(text="zażółć\nline"))
    head, data, blank, end = frame.split("\n")
    assert head == "event: token"
    assert json.loads(data.removeprefix("data: ")) == {"event": "token", "text": "zażółć\nline"}
    assert (blank, end) == ("", "")


def test_status_event_defaults() -> None:
    assert StatusEvent(phase="retrieving").model_dump() == {
        "event": "status",
        "phase": "retrieving",
        "endpoint": None,
        "model": None,
        "degraded": None,
    }


def test_turn_event_stream_schema_requires_event_field() -> None:
    schema = TurnEventStream.model_json_schema(mode="serialization")
    for name in ("StatusEvent", "ReceiptEvent", "ErrorEvent"):
        assert "event" in schema["$defs"][name]["required"]


def test_receipt_and_error_round_trip() -> None:
    receipt = ReceiptEvent(
        turn_id=uuid4(), seq=1, endpoint="ws", model="m", degraded=False, duration_ms=12
    )
    assert json.loads(receipt.model_dump_json())["event"] == "receipt"
    error = ErrorEvent(code="no_local_model", component="ollama", message="x")
    assert error.event == "error"

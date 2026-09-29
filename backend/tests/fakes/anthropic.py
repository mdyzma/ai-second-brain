"""Scriptable fake of Anthropic's streaming Messages API that records requests."""

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from .ollama import RecordedRequest
from .server import ServerThread


@dataclass
class AnthropicBehaviour:
    status: int = 200
    error_type: str = "api_error"
    error_message: str = "boom"
    chunks: list[str] = field(default_factory=lambda: ["Hello", " from", " cloud"])
    first_chunk_delay: float = 0.0
    send_stop: bool = True


def _sse(name: str, payload: dict[str, Any]) -> bytes:
    return f"event: {name}\ndata: {json.dumps(payload)}\n\n".encode()


class FakeAnthropic:
    def __init__(self) -> None:
        self.behaviour = AnthropicBehaviour()
        self.requests: list[RecordedRequest] = []
        app = Starlette(routes=[Route("/v1/messages", self._messages, methods=["POST"])])
        self._server = ServerThread(app)
        self.url = self._server.url

    def start(self) -> "FakeAnthropic":
        self._server.start()
        return self

    def stop(self) -> None:
        self._server.stop()

    async def _messages(self, request: Request) -> Response:
        body = json.loads(await request.body())
        self.requests.append(RecordedRequest("POST", "/v1/messages", body, dict(request.headers)))
        b = self.behaviour
        if b.status != 200:
            error = {"type": "error", "error": {"type": b.error_type, "message": b.error_message}}
            return JSONResponse(error, status_code=b.status)

        async def stream() -> AsyncIterator[bytes]:
            yield _sse(
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": "msg_fake",
                        "type": "message",
                        "role": "assistant",
                        "model": body["model"],
                        "content": [],
                        "stop_reason": None,
                        "stop_sequence": None,
                        "usage": {"input_tokens": 1, "output_tokens": 0},
                    },
                },
            )
            block = {"type": "text", "text": ""}
            yield _sse(
                "content_block_start",
                {"type": "content_block_start", "index": 0, "content_block": block},
            )
            if b.first_chunk_delay:
                await asyncio.sleep(b.first_chunk_delay)
            for text in b.chunks:
                delta = {"type": "text_delta", "text": text}
                yield _sse(
                    "content_block_delta",
                    {"type": "content_block_delta", "index": 0, "delta": delta},
                )
            yield _sse("content_block_stop", {"type": "content_block_stop", "index": 0})
            if b.send_stop:
                yield _sse(
                    "message_delta",
                    {
                        "type": "message_delta",
                        "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                        "usage": {"output_tokens": len(b.chunks)},
                    },
                )
                yield _sse("message_stop", {"type": "message_stop"})

        return StreamingResponse(stream(), media_type="text/event-stream")

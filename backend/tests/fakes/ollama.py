"""Scriptable fake Ollama (`/api/version`, streamed `/api/chat`) that records requests."""

import asyncio
import json
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response, StreamingResponse
from starlette.routing import Route

from .server import ServerThread


@dataclass
class RecordedRequest:
    method: str
    path: str
    body: Any
    headers: dict[str, str]


@dataclass
class OllamaBehaviour:
    probe_status: int = 200
    chat_status: int = 200
    error_text: str = "internal error"
    redirect_to: str | None = None
    chunks: list[str] = field(default_factory=lambda: ["Hello", " from", " Ollama"])
    first_chunk_delay: float = 0.0
    chunk_delay: float = 0.0
    send_done: bool = True
    malformed_after: int | None = None  # replace chunk N with a non-JSON line
    error_line_after: int | None = None  # replace chunk N with {"error": error_text}


class FakeOllama:
    def __init__(self) -> None:
        self.behaviour = OllamaBehaviour()
        self.requests: list[RecordedRequest] = []
        self.stream_closed_early = threading.Event()
        self.stream_finished = threading.Event()
        app = Starlette(
            routes=[
                Route("/api/version", self._version, methods=["GET"]),
                Route("/api/chat", self._chat, methods=["POST"]),
                Route("/{path:path}", self._other, methods=["GET", "POST"]),
            ]
        )
        self._server = ServerThread(app)
        self.url = self._server.url

    def start(self) -> "FakeOllama":
        self._server.start()
        return self

    def stop(self) -> None:
        self._server.stop()

    def chat_requests(self) -> list[RecordedRequest]:
        return [r for r in self.requests if r.path == "/api/chat"]

    async def _record(self, request: Request) -> Any:
        raw = await request.body()
        body = json.loads(raw) if raw else None
        self.requests.append(
            RecordedRequest(request.method, request.url.path, body, dict(request.headers))
        )
        return body

    async def _version(self, request: Request) -> Response:
        await self._record(request)
        if self.behaviour.probe_status != 200:
            return Response(status_code=self.behaviour.probe_status)
        return JSONResponse({"version": "0.0.0-fake"})

    async def _other(self, request: Request) -> Response:
        await self._record(request)
        return Response(status_code=404)

    async def _chat(self, request: Request) -> Response:
        body = await self._record(request)
        b = self.behaviour
        if b.redirect_to is not None:
            return RedirectResponse(b.redirect_to, status_code=307)
        if b.chat_status != 200:
            return JSONResponse({"error": b.error_text}, status_code=b.chat_status)
        model = body["model"]

        def line(payload: dict[str, Any]) -> bytes:
            return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")

        async def stream() -> AsyncIterator[bytes]:
            completed = False
            try:
                if b.first_chunk_delay:
                    await asyncio.sleep(b.first_chunk_delay)
                for index, text in enumerate(b.chunks):
                    if index and b.chunk_delay:
                        await asyncio.sleep(b.chunk_delay)
                    if b.malformed_after == index:
                        yield b"{not json\n"
                        completed = True
                        return
                    if b.error_line_after == index:
                        yield line({"error": b.error_text})
                        completed = True
                        return
                    message = {"role": "assistant", "content": text}
                    yield line({"model": model, "message": message, "done": False})
                if b.send_done:
                    message = {"role": "assistant", "content": ""}
                    yield line({"model": model, "message": message, "done": True})
                completed = True
            finally:
                (self.stream_finished if completed else self.stream_closed_early).set()

        return StreamingResponse(stream(), media_type="application/x-ndjson")

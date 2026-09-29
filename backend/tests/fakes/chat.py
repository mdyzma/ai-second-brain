"""In-process chat doubles for service tests (the HTTP fakes cover the wire)."""

import asyncio
from collections.abc import AsyncIterator, Sequence

from ai_second_brain.chat.errors import ChatError, Component
from ai_second_brain.chat.models import ChatMessage, Source


class ScriptedProvider:
    def __init__(
        self,
        chunks: Sequence[str] = ("Hello", " there"),
        *,
        label: str = "workstation",
        model: str = "qwen3:32b",
        degraded: bool = False,
        component: Component = "ollama",
        error: ChatError | None = None,
        error_after: int = 0,
        gate: asyncio.Event | None = None,
    ) -> None:
        self.chunks = list(chunks)
        self._label, self._model, self._degraded = label, model, degraded
        self._component: Component = component
        self.error, self.error_after, self.gate = error, error_after, gate
        self.calls: list[tuple[str, list[ChatMessage]]] = []

    @property
    def label(self) -> str:
        return self._label

    @property
    def model(self) -> str:
        return self._model

    @property
    def degraded(self) -> bool:
        return self._degraded

    @property
    def component(self) -> Component:
        return self._component

    async def stream(self, system: str, messages: Sequence[ChatMessage]) -> AsyncIterator[str]:
        self.calls.append((system, list(messages)))
        for index, chunk in enumerate(self.chunks):
            if self.error is not None and index == self.error_after:
                raise self.error
            if self.gate is not None:
                await self.gate.wait()
            yield chunk
        if self.error is not None and self.error_after >= len(self.chunks):
            raise self.error


class StubPool:
    def __init__(self, result: ScriptedProvider | ChatError) -> None:
        self.result = result
        self.selects = 0

    async def select(self) -> ScriptedProvider:
        self.selects += 1
        if isinstance(self.result, ChatError):
            raise self.result
        return self.result


class StaticRetriever:
    def __init__(self, sources: Sequence[Source]) -> None:
        self.sources = list(sources)
        self.calls: list[tuple[str, int]] = []

    async def retrieve(self, question: str, limit: int) -> list[Source]:
        self.calls.append((question, limit))
        return self.sources


class SpyRetriever(StaticRetriever):
    """Fails the test if cloud code ever retrieves."""

    async def retrieve(self, question: str, limit: int) -> list[Source]:
        raise AssertionError("retriever must not be called")


class FailingRetriever:
    async def retrieve(self, question: str, limit: int) -> list[Source]:
        raise RuntimeError("index unavailable")

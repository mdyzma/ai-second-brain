"""Provider contract shared by the local (Ollama) and cloud (Anthropic) providers."""

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Protocol

import httpx2

from ai_second_brain.chat.errors import Component
from ai_second_brain.chat.models import ChatMessage


@dataclass(frozen=True, slots=True)
class ChatTimeouts:
    connect: float = 5.0
    read: float = 120.0  # between chunks, not for the whole answer
    probe: float = 1.0

    def http(self) -> httpx2.Timeout:
        return httpx2.Timeout(
            connect=self.connect, read=self.read, write=self.connect, pool=self.connect
        )


class ChatProvider(Protocol):
    @property
    def label(self) -> str: ...
    @property
    def model(self) -> str: ...
    @property
    def degraded(self) -> bool: ...
    @property
    def component(self) -> Component: ...

    def stream(self, system: str, messages: Sequence[ChatMessage]) -> AsyncIterator[str]:
        """Yield answer text chunks. Raise ChatError; never return a partial answer silently."""
        ...

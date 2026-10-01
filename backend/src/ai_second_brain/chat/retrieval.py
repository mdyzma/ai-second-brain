"""Retrieval seam: the chat service asks for evidence and learns how it was found."""

from dataclasses import dataclass
from typing import Literal, Protocol

from ai_second_brain.chat.models import Source

RetrievalMode = Literal["hybrid", "text_only", "none"]


@dataclass(frozen=True)
class Retrieval:
    sources: list[Source]
    mode: RetrievalMode


class Retriever(Protocol):
    async def retrieve(self, question: str, limit: int) -> Retrieval: ...


class NullRetriever:
    async def retrieve(self, question: str, limit: int) -> Retrieval:
        return Retrieval([], "none")

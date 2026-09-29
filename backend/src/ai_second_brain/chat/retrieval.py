"""Retrieval seam. Phase 2 provides the real implementation; until then nothing is found."""

from typing import Protocol

from ai_second_brain.chat.models import Source


class Retriever(Protocol):
    async def retrieve(self, question: str, limit: int) -> list[Source]: ...


class NullRetriever:
    async def retrieve(self, question: str, limit: int) -> list[Source]:
        return []

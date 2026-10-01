"""Embed one query for search or chat: 1.5 s cap, then a 30 s breaker. Logs codes only."""

import asyncio
import html
import logging
import time
from collections.abc import Callable
from typing import Protocol

from ai_second_brain.knowledge.embedder import EmbedError

logger = logging.getLogger("ai_second_brain.search")


class _Embeds(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class QueryEmbedder:
    def __init__(
        self,
        embedder: _Embeds | None,
        *,
        timeout: float = 1.5,
        cooldown: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._embedder, self._timeout, self._cooldown, self._clock = (
            embedder,
            timeout,
            cooldown,
            clock,
        )
        self._down_until = 0.0

    async def embed(self, text: str) -> list[float] | None:
        if self._embedder is None or self._clock() < self._down_until:
            return None
        try:
            async with asyncio.timeout(self._timeout):
                [vector] = await self._embedder.embed([text])
        except (EmbedError, TimeoutError, ValueError) as error:
            code = error.code if isinstance(error, EmbedError) else "embed_timeout"
            logger.warning("query_embed_unavailable code=%s", code)
            self._down_until = self._clock() + self._cooldown
            return None
        return vector


def excerpt(content: str, limit: int = 240) -> str:
    # Escape first, then cut at a space; a cut inside a space-free run drops a partial entity.
    text = html.escape(" ".join(content.split()), quote=False)
    if len(text) > limit:
        cut = text[:limit]
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        amp = cut.rfind("&")
        if amp != -1 and ";" not in cut[amp:]:
            cut = cut[:amp]
        text = cut + "…"
    return text

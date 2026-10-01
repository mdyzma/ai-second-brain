"""Embed one query for search or chat: a time cap, then a breaker. Logs codes only.

A timeout opens the breaker briefly (the model may still be loading); an embed error
(host unreachable, model missing, bad response) opens it for longer. Query embeds ask
Ollama to keep the model loaded so the owner's next search is not a cold load.
"""

import asyncio
import html
import logging
import time
from collections.abc import Callable
from typing import Protocol

from ai_second_brain.knowledge.embedder import EmbedError

logger = logging.getLogger("ai_second_brain.search")

QUERY_KEEP_ALIVE = "30m"


class _Embeds(Protocol):
    async def embed(
        self, texts: list[str], *, keep_alive: str | None = None
    ) -> list[list[float]]: ...


class QueryEmbedder:
    def __init__(
        self,
        embedder: _Embeds | None,
        *,
        timeout: float = 1.5,
        cooldown: float = 30.0,
        timeout_cooldown: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._embedder, self._timeout, self._clock = embedder, timeout, clock
        self._cooldown, self._timeout_cooldown = cooldown, timeout_cooldown
        self._down_until = 0.0

    async def embed(self, text: str, *, timeout: float | None = None) -> list[float] | None:  # noqa: ASYNC109 - a cap applied with asyncio.timeout inside
        if self._embedder is None or self._clock() < self._down_until:
            return None
        try:
            async with asyncio.timeout(self._timeout if timeout is None else timeout):
                [vector] = await self._embedder.embed([text], keep_alive=QUERY_KEEP_ALIVE)
        except TimeoutError:
            logger.warning("query_embed_unavailable code=embed_timeout")
            self._down_until = self._clock() + self._timeout_cooldown
            return None
        except (EmbedError, ValueError) as error:
            code = error.code if isinstance(error, EmbedError) else "embed_bad_response"
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

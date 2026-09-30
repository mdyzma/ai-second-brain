"""Ollama /api/embed client. Content-free errors; no redirects, proxies or cloud fallback."""

import math
from collections.abc import Sequence
from typing import Literal

import httpx2

from ai_second_brain.chat.providers.base import ChatTimeouts

EmbedCode = Literal["embed_unreachable", "embed_model_missing", "embed_bad_response"]


class EmbedError(Exception):
    def __init__(self, code: EmbedCode) -> None:
        super().__init__(code)
        self.code: EmbedCode = code


class EmbedRetryable(Exception):  # noqa: N818 - name fixed by the task interface
    """embed_unreachable inside the embedding job: procrastinate retries it (Task 7)."""


class Embedder:
    def __init__(
        self, url: str, model: str, dims: int, client: httpx2.AsyncClient, timeouts: ChatTimeouts
    ) -> None:
        self.url, self.model, self.dims = url, model, dims
        self._client, self._timeouts = client, timeouts

    async def reachable(self) -> bool:
        try:
            response = await self._client.get(
                f"{self.url}/api/version", timeout=self._timeouts.probe
            )
        except (httpx2.HTTPError, httpx2.InvalidURL):
            return False
        return 200 <= response.status_code < 300

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        try:
            response = await self._client.post(
                f"{self.url}/api/embed",
                json={"model": self.model, "input": list(texts)},
                timeout=self._timeouts.http(),
            )
        except (httpx2.TimeoutException, httpx2.TransportError):
            raise EmbedError("embed_unreachable") from None
        if response.status_code >= 500:
            raise EmbedError("embed_unreachable")
        if response.status_code == 404 and "model" in response.text.lower():
            raise EmbedError("embed_model_missing")
        if response.status_code != 200:
            raise EmbedError("embed_bad_response")
        try:
            vectors = response.json()["embeddings"]
        except (ValueError, KeyError, TypeError):
            raise EmbedError("embed_bad_response") from None
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise EmbedError("embed_bad_response")
        return [self._checked(vector) for vector in vectors]

    def _checked(self, vector: object) -> list[float]:
        if not isinstance(vector, list) or len(vector) != self.dims:
            raise EmbedError("embed_bad_response")
        values: list[float] = []
        for v in vector:
            if isinstance(v, bool) or not isinstance(v, int | float):
                raise EmbedError("embed_bad_response")
            try:
                number = float(v)
            except OverflowError:
                raise EmbedError("embed_bad_response") from None
            if not math.isfinite(number):
                raise EmbedError("embed_bad_response")
            values.append(number)
        return values

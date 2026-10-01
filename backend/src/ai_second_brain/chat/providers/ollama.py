"""Ollama on the owner's LAN: ordered endpoints, first reachable wins, streamed /api/chat."""

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from typing import Any

import httpx2

from ai_second_brain.chat.errors import ChatError, Component, ErrorCode
from ai_second_brain.chat.models import ChatMessage
from ai_second_brain.chat.providers.base import ChatTimeouts
from ai_second_brain.config import OllamaEndpointConfig

CONTEXT_ERROR = re.compile(r"context", re.IGNORECASE)


def create_http_client() -> httpx2.AsyncClient:
    """Private-tier client: never follows redirects, ignores proxy and other env settings."""
    return httpx2.AsyncClient(follow_redirects=False, trust_env=False)


@dataclass(frozen=True, slots=True)
class EndpointStatus:
    label: str
    model: str
    degraded: bool
    reachable: bool


def _failure(text: str) -> ErrorCode:
    return "context_too_long" if CONTEXT_ERROR.search(text) else "provider_error"


class OllamaProvider:
    def __init__(
        self,
        endpoint: OllamaEndpointConfig,
        client: httpx2.AsyncClient,
        timeouts: ChatTimeouts,
        max_tokens: int,
        *,
        num_ctx: int,
    ) -> None:
        self._endpoint = endpoint
        self._client = client
        self._timeouts = timeouts
        self._max_tokens = max_tokens
        self._num_ctx = num_ctx

    @property
    def label(self) -> str:
        return self._endpoint.label

    @property
    def model(self) -> str:
        return self._endpoint.model

    @property
    def degraded(self) -> bool:
        return self._endpoint.degraded

    @property
    def component(self) -> Component:
        return "ollama"

    async def stream(self, system: str, messages: Sequence[ChatMessage]) -> AsyncIterator[str]:
        payload = {
            "model": self._endpoint.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "stream": True,
            "options": {"num_predict": self._max_tokens, "num_ctx": self._num_ctx},
        }
        done = False
        try:
            async with self._client.stream(
                "POST",
                f"{self._endpoint.url}/api/chat",
                json=payload,
                timeout=self._timeouts.http(),
            ) as response:
                if response.status_code != 200:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    code = _failure(body) if 400 <= response.status_code < 500 else None
                    raise ChatError(code or "provider_error", "ollama")
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    data = _parse(line)
                    if "error" in data:
                        raise ChatError(_failure(str(data["error"])), "ollama")
                    message = data.get("message")
                    content = message.get("content") if isinstance(message, dict) else None
                    if isinstance(content, str) and content:
                        yield content
                    if data.get("done") is True:
                        done = True
                        break
        except httpx2.TimeoutException:
            raise ChatError("provider_timeout", "ollama") from None
        except httpx2.HTTPError:
            raise ChatError("provider_error", "ollama") from None
        if not done:
            raise ChatError("provider_error", "ollama")


def _parse(line: str) -> dict[str, Any]:
    try:
        data = json.loads(line)
    except ValueError:
        raise ChatError("provider_error", "ollama") from None
    if not isinstance(data, dict):
        raise ChatError("provider_error", "ollama")
    return data


class OllamaPool:
    def __init__(
        self,
        endpoints: Sequence[OllamaEndpointConfig],
        client: httpx2.AsyncClient,
        *,
        timeouts: ChatTimeouts,
        max_tokens: int,
        num_ctx: int,
        status_ttl: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._endpoints = list(endpoints)
        self._client = client
        self._timeouts = timeouts
        self._max_tokens = max_tokens
        self._num_ctx = num_ctx
        self._status_ttl = status_ttl
        self._clock = clock
        self._cache: tuple[float, list[EndpointStatus]] | None = None

    @property
    def endpoints(self) -> list[OllamaEndpointConfig]:
        return list(self._endpoints)

    async def _probe(self, endpoint: OllamaEndpointConfig) -> bool:
        try:
            response = await self._client.get(
                f"{endpoint.url}/api/version", timeout=self._timeouts.probe
            )
        except (httpx2.HTTPError, httpx2.InvalidURL):
            return False
        return 200 <= response.status_code < 300

    async def select(self) -> OllamaProvider:
        """First endpoint whose probe answers, in configured order. No cloud, ever."""
        for endpoint in self._endpoints:
            if await self._probe(endpoint):
                return OllamaProvider(
                    endpoint,
                    self._client,
                    self._timeouts,
                    self._max_tokens,
                    num_ctx=self._num_ctx,
                )
        raise ChatError("no_local_model", "ollama")

    async def status(self) -> list[EndpointStatus]:
        now = self._clock()
        if self._cache is not None and now - self._cache[0] < self._status_ttl:
            return self._cache[1]
        results = await asyncio.gather(*(self._probe(e) for e in self._endpoints))
        statuses = [
            EndpointStatus(e.label, e.model, e.degraded, ok)
            for e, ok in zip(self._endpoints, results, strict=True)
        ]
        self._cache = (now, statuses)
        return statuses

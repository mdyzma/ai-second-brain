"""Non-streaming Ollama /api/chat with a JSON-schema format. Local endpoints only."""

from collections.abc import Sequence
from typing import Any

import httpx2

from ai_second_brain.chat.providers.base import ChatTimeouts
from ai_second_brain.config import OllamaEndpointConfig, local_model_name


class ExtractUnreachable(Exception):  # noqa: N818 - name is the cross-task contract
    pass


class ExtractClient:
    def __init__(
        self,
        client: httpx2.AsyncClient,
        endpoints: Sequence[OllamaEndpointConfig],
        model: str,
        timeouts: ChatTimeouts,
        num_ctx: int,
        read_timeout: float = 600.0,
    ) -> None:
        self._client, self._endpoints = client, list(endpoints)
        self._model, self._timeouts, self._num_ctx = local_model_name(model), timeouts, num_ctx
        self._read_timeout = read_timeout

    @property
    def model(self) -> str:
        return self._model

    async def chat_json(self, messages: list[dict[str, str]], schema: dict[str, Any]) -> str:
        body = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "format": schema,
            "keep_alive": "30m",
            "options": {"temperature": 0, "num_ctx": self._num_ctx},
        }
        for endpoint in self._endpoints:
            try:
                response = await self._client.post(
                    f"{endpoint.url}/api/chat",
                    json=body,
                    timeout=httpx2.Timeout(
                        connect=self._timeouts.connect,
                        read=self._read_timeout,  # the whole non-streamed call
                        write=self._timeouts.connect,
                        pool=self._timeouts.connect,
                    ),
                )
            except (httpx2.TimeoutException, httpx2.TransportError):
                continue
            if response.status_code >= 500 or response.status_code == 404:
                continue
            if response.status_code != 200:
                raise ExtractUnreachable(f"status {response.status_code}")
            try:
                content = response.json()["message"]["content"]
            except (ValueError, KeyError, TypeError):
                return ""
            return content if isinstance(content, str) else ""
        raise ExtractUnreachable("no local endpoint answered")

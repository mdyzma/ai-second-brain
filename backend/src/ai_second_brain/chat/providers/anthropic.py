"""Anthropic (cloud tier). Imported lazily by chat/wiring.py, only for cloud sessions."""

import logging
import re
from collections.abc import AsyncIterator, Sequence

import anthropic
import httpx2

from ai_second_brain.chat.errors import ChatError, Component
from ai_second_brain.chat.models import ChatMessage
from ai_second_brain.chat.providers.base import ChatTimeouts

# The SDK logs request options (message text included) at DEBUG. Never let that through.
logging.getLogger("anthropic").setLevel(logging.WARNING)

PROMPT_TOO_LONG = re.compile(r"prompt is too long", re.IGNORECASE)


class AnthropicProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        max_tokens: int,
        timeouts: ChatTimeouts,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url
        self._max_tokens = max_tokens
        self._timeouts = timeouts

    @property
    def label(self) -> str:
        return "anthropic"

    @property
    def model(self) -> str:
        return self._model

    @property
    def degraded(self) -> bool:
        return False

    @property
    def component(self) -> Component:
        return "anthropic"

    async def stream(self, system: str, messages: Sequence[ChatMessage]) -> AsyncIterator[str]:
        stopped = False
        timeout = self._timeouts.http()
        async with httpx2.AsyncClient(
            follow_redirects=False, trust_env=False, timeout=timeout
        ) as http_client:
            client = anthropic.AsyncAnthropic(
                api_key=self._api_key,
                base_url=self._base_url,
                max_retries=0,
                timeout=timeout,
                http_client=http_client,
            )
            try:
                async with client.messages.stream(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    system=system,
                    messages=[{"role": m["role"], "content": m["content"]} for m in messages],
                ) as stream:
                    async for event in stream:
                        if event.type == "text" and event.text:
                            yield event.text
                        elif event.type == "message_stop":
                            stopped = True
            except (anthropic.APITimeoutError, httpx2.TimeoutException):
                # Mid-stream read timeouts surface as raw httpx2 errors, not SDK ones.
                raise ChatError("provider_timeout", "anthropic") from None
            except (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
                raise ChatError("cloud_auth", "anthropic") from None
            except (anthropic.RateLimitError, anthropic.OverloadedError):
                raise ChatError("cloud_rate_limited", "anthropic") from None
            except anthropic.BadRequestError as error:
                too_long = PROMPT_TOO_LONG.search(str(error.message))
                raise ChatError(
                    "context_too_long" if too_long else "provider_error", "anthropic"
                ) from None
            except anthropic.APIStatusError as error:
                code = "cloud_rate_limited" if error.status_code == 529 else "provider_error"
                raise ChatError(code, "anthropic") from None
            except (anthropic.APIError, httpx2.HTTPError):
                raise ChatError("provider_error", "anthropic") from None
        if not stopped:
            raise ChatError("provider_error", "anthropic")

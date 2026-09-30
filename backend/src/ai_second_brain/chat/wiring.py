"""Builds the cloud provider on demand. The only importer of the Anthropic module."""

from collections.abc import Callable

from ai_second_brain.chat.providers.base import ChatProvider, ChatTimeouts
from ai_second_brain.config import Settings


def make_cloud_factory(
    settings: Settings, timeouts: ChatTimeouts
) -> Callable[[], ChatProvider] | None:
    if not settings.cloud_available:
        return None
    api_key = settings.anthropic_api_key.get_secret_value().strip()

    def build() -> ChatProvider:
        # Lazy on purpose: private code paths must never import the anthropic package.
        from ai_second_brain.chat.providers.anthropic import AnthropicProvider

        return AnthropicProvider(
            api_key=api_key,
            model=settings.anthropic_model,
            base_url=settings.anthropic_base_url,
            max_tokens=settings.chat_max_tokens,
            timeouts=timeouts,
        )

    return build

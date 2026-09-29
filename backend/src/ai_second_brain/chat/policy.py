"""The single routing decision. Private never reaches the cloud; there is no fallback."""

from typing import assert_never

from ai_second_brain.chat.models import ChatMode, Tier


def route(mode: ChatMode) -> Tier:
    match mode:
        case ChatMode.PRIVATE:
            return Tier.LOCAL
        case ChatMode.CLOUD:
            return Tier.CLOUD
        case _:
            assert_never(mode)

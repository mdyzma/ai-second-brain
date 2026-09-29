from ai_second_brain.chat.models import ChatMode, Tier
from ai_second_brain.chat.policy import route


def test_every_mode_routes_to_exactly_one_tier() -> None:
    assert {mode: route(mode) for mode in ChatMode} == {
        ChatMode.PRIVATE: Tier.LOCAL,
        ChatMode.CLOUD: Tier.CLOUD,
    }

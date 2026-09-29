from typing import get_args

from ai_second_brain.chat.errors import MESSAGES, ChatError, ErrorCode, error_message
from ai_second_brain.chat.models import ChatMode


def test_every_code_has_a_message() -> None:
    assert set(MESSAGES) == set(get_args(ErrorCode))


def test_private_messages_promise_no_cloud_and_cloud_messages_do_not() -> None:
    for code in MESSAGES:
        assert error_message(code, ChatMode.PRIVATE).endswith("Nothing was sent to the cloud.")
        assert "Nothing was sent" not in error_message(code, ChatMode.CLOUD)


def test_chat_error_carries_code_and_component_only() -> None:
    error = ChatError("provider_timeout", "ollama")
    assert (error.code, error.component) == ("provider_timeout", "ollama")
    assert str(error) == "provider_timeout"

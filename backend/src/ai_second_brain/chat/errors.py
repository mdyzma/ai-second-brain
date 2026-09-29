"""Content-free chat errors: a code, the failing component and a fixed sentence."""

from typing import Literal

from ai_second_brain.chat.models import ChatMode

ErrorCode = Literal[
    "no_local_model",
    "provider_timeout",
    "provider_error",
    "context_too_long",
    "cloud_auth",
    "cloud_rate_limited",
    "cloud_unavailable",
    "retrieval_error",
    "storage_error",
    "turn_in_progress",
]
Component = Literal["ollama", "anthropic", "retrieval", "db", "chat"]

PRIVATE_SUFFIX = "Nothing was sent to the cloud."

MESSAGES: dict[ErrorCode, str] = {
    "no_local_model": "No local model is reachable.",
    "provider_timeout": "The model did not respond in time.",
    "provider_error": "The model returned an invalid or incomplete response.",
    "context_too_long": (
        "The conversation is too long for the model's context window. Start a new session."
    ),
    "cloud_auth": "Anthropic rejected the API key.",
    "cloud_rate_limited": "Anthropic is rate-limiting or overloaded. Try again shortly.",
    "cloud_unavailable": "Cloud mode is not configured.",
    "retrieval_error": "Searching your notes failed.",
    "storage_error": "The answer could not be saved.",
    "turn_in_progress": "Another answer is still being generated in this session.",
}


class ChatError(Exception):
    def __init__(self, code: ErrorCode, component: Component) -> None:
        super().__init__(code)
        self.code: ErrorCode = code
        self.component: Component = component


def error_message(code: ErrorCode, mode: ChatMode) -> str:
    message = MESSAGES[code]
    return f"{message} {PRIVATE_SUFFIX}" if mode is ChatMode.PRIVATE else message

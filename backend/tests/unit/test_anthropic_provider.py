import logging
from collections.abc import Callable

import pytest

from ai_second_brain.chat.errors import ChatError
from ai_second_brain.chat.models import ChatMessage
from ai_second_brain.chat.providers.base import ChatTimeouts
from ai_second_brain.chat.wiring import make_cloud_factory
from ai_second_brain.config import Settings

from ..conftest import run_async
from ..fakes.anthropic import FakeAnthropic

FAST = ChatTimeouts(connect=1.0, read=0.5, probe=0.5)
QUESTION = "unique-cloud-question-7f3a"
MESSAGES: list[ChatMessage] = [{"role": "user", "content": QUESTION}]
MakeFake = Callable[[], FakeAnthropic]


def settings_for(make_settings: Callable[..., Settings], fake: FakeAnthropic) -> Settings:
    return make_settings(
        anthropic_api_key="sk-fake", anthropic_base_url=fake.url, anthropic_model="claude-test"
    )


def collect(settings: Settings) -> str:
    factory = make_cloud_factory(settings, FAST)
    assert factory is not None
    provider = factory()

    async def scenario() -> str:
        return "".join([part async for part in provider.stream("CLOUD SYSTEM", MESSAGES)])

    return run_async(scenario())


def test_factory_is_none_without_key(make_settings: Callable[..., Settings]) -> None:
    assert make_cloud_factory(make_settings(), FAST) is None


def test_streams_text_and_sends_expected_request(
    make_settings: Callable[..., Settings], make_fake_anthropic: MakeFake
) -> None:
    fake = make_fake_anthropic()
    assert collect(settings_for(make_settings, fake)) == "Hello from cloud"
    [request] = fake.requests
    assert request.body["model"] == "claude-test"
    assert request.body["max_tokens"] == 2048
    assert request.body["system"] == "CLOUD SYSTEM"
    assert request.body["messages"] == MESSAGES
    assert request.headers["x-api-key"] == "sk-fake"


@pytest.mark.parametrize(
    ("status", "error_type", "message", "code"),
    [
        (401, "authentication_error", "invalid x-api-key", "cloud_auth"),
        (403, "permission_error", "no", "cloud_auth"),
        (429, "rate_limit_error", "slow down", "cloud_rate_limited"),
        (529, "overloaded_error", "overloaded", "cloud_rate_limited"),
        (400, "invalid_request_error", "prompt is too long: 250000 > 200000", "context_too_long"),
        (400, "invalid_request_error", "bad field", "provider_error"),
        (500, "api_error", "boom", "provider_error"),
    ],
)
def test_errors_map_to_codes_without_retries(
    make_settings: Callable[..., Settings],
    make_fake_anthropic: MakeFake,
    status: int,
    error_type: str,
    message: str,
    code: str,
) -> None:
    fake = make_fake_anthropic()
    fake.behaviour.status, fake.behaviour.error_type = status, error_type
    fake.behaviour.error_message = message
    with pytest.raises(ChatError) as error:
        collect(settings_for(make_settings, fake))
    assert (error.value.code, error.value.component) == (code, "anthropic")
    assert len(fake.requests) == 1  # max_retries=0


def test_missing_message_stop_is_an_error(
    make_settings: Callable[..., Settings], make_fake_anthropic: MakeFake
) -> None:
    fake = make_fake_anthropic()
    fake.behaviour.send_stop = False
    with pytest.raises(ChatError) as error:
        collect(settings_for(make_settings, fake))
    assert error.value.code == "provider_error"


def test_slow_first_chunk_times_out(
    make_settings: Callable[..., Settings], make_fake_anthropic: MakeFake
) -> None:
    fake = make_fake_anthropic()
    fake.behaviour.first_chunk_delay = 2.0
    with pytest.raises(ChatError) as error:
        collect(settings_for(make_settings, fake))
    assert error.value.code == "provider_timeout"


def test_sdk_debug_logging_never_carries_the_question(
    make_settings: Callable[..., Settings],
    make_fake_anthropic: MakeFake,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    fake = make_fake_anthropic()
    collect(settings_for(make_settings, fake))
    assert QUESTION not in caplog.text
    assert "sk-fake" not in caplog.text


def test_ambient_anthropic_env_cannot_redirect_or_add_auth(
    make_settings: Callable[..., Settings],
    make_fake_anthropic: MakeFake,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake, other = make_fake_anthropic(), make_fake_anthropic()
    monkeypatch.setenv("ANTHROPIC_BASE_URL", other.url)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "ambient-token")
    assert collect(settings_for(make_settings, fake)) == "Hello from cloud"
    assert other.requests == []
    [request] = fake.requests
    assert request.headers["x-api-key"] == "sk-fake"
    assert "authorization" not in {name.lower() for name in request.headers}

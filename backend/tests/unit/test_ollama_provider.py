import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import cast

import httpx2
import pytest

from ai_second_brain.chat.errors import ChatError
from ai_second_brain.chat.models import ChatMessage
from ai_second_brain.chat.providers.base import ChatTimeouts
from ai_second_brain.chat.providers.ollama import OllamaPool, create_http_client
from ai_second_brain.config import OllamaEndpointConfig

from ..conftest import run_async
from ..fakes.ollama import FakeOllama
from ..fakes.server import closed_port_url

FAST = ChatTimeouts(connect=1.0, read=0.5, probe=0.5)
MESSAGES: list[ChatMessage] = [{"role": "user", "content": "Hi"}]
MakeFake = Callable[[], FakeOllama]
PoolBody = Callable[[OllamaPool], Awaitable[None]]


def endpoint(url: str, label: str = "ws", *, degraded: bool = False) -> OllamaEndpointConfig:
    return OllamaEndpointConfig(label=label, url=url, model="fake-model", degraded=degraded)


async def collect(pool: OllamaPool) -> str:
    provider = await pool.select()
    return "".join([part async for part in provider.stream("SYSTEM", MESSAGES)])


def make_pool(
    *endpoints: OllamaEndpointConfig, clock: Callable[[], float] = time.monotonic
) -> tuple[OllamaPool, httpx2.AsyncClient]:
    client = create_http_client()
    pool = OllamaPool(
        list(endpoints), client, timeouts=FAST, max_tokens=321, status_ttl=10.0, clock=clock
    )
    return pool, client


def run_with_pool(*endpoints: OllamaEndpointConfig, body: PoolBody) -> None:
    async def scenario() -> None:
        pool, client = make_pool(*endpoints)
        async with client:
            await body(pool)

    run_async(scenario())


def test_select_prefers_first_reachable_in_order(make_fake_ollama: MakeFake) -> None:
    first, second = make_fake_ollama(), make_fake_ollama()
    first.behaviour.probe_status = 503

    async def body(pool: OllamaPool) -> None:
        provider = await pool.select()
        assert (provider.label, provider.degraded) == ("proxmox", True)

    run_with_pool(
        endpoint(closed_port_url(), "down"),
        endpoint(first.url, "busy"),
        endpoint(second.url, "proxmox", degraded=True),
        body=body,
    )
    assert [r.path for r in first.requests] == ["/api/version"]


def test_select_without_reachable_endpoint_raises(make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    fake.behaviour.probe_status = 302  # redirects are not followed, so not "reachable"

    async def body(pool: OllamaPool) -> None:
        with pytest.raises(ChatError) as error:
            await pool.select()
        assert (error.value.code, error.value.component) == ("no_local_model", "ollama")

    run_with_pool(endpoint(fake.url), endpoint(closed_port_url(), "b"), body=body)
    assert fake.chat_requests() == []


def test_stream_sends_expected_payload(make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()

    async def body(pool: OllamaPool) -> None:
        assert await collect(pool) == "Hello from Ollama"

    run_with_pool(endpoint(fake.url), body=body)
    [request] = fake.chat_requests()
    assert request.body == {
        "model": "fake-model",
        "messages": [{"role": "system", "content": "SYSTEM"}, *MESSAGES],
        "stream": True,
        "options": {"num_predict": 321},
    }


def test_stream_keeps_multibyte_text_split_across_chunks(make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    fake.behaviour.chunks = ["zażółć ", "gęślą ", "jaźń"]

    async def body(pool: OllamaPool) -> None:
        assert await collect(pool) == "zażółć gęślą jaźń"

    run_with_pool(endpoint(fake.url), body=body)


@pytest.mark.parametrize(
    ("status", "text", "code"),
    [
        (500, "internal error", "provider_error"),
        (404, "model 'fake-model' not found, try pulling it first", "provider_error"),
        (400, "input length exceeds the context length", "context_too_long"),
    ],
)
def test_chat_status_errors_map_to_codes(
    make_fake_ollama: MakeFake, status: int, text: str, code: str
) -> None:
    fake = make_fake_ollama()
    fake.behaviour.chat_status, fake.behaviour.error_text = status, text

    async def body(pool: OllamaPool) -> None:
        with pytest.raises(ChatError) as error:
            await collect(pool)
        assert error.value.code == code

    run_with_pool(endpoint(fake.url), body=body)


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"malformed_after": 1}, "provider_error"),
        ({"error_line_after": 1}, "provider_error"),
        ({"error_line_after": 1, "error_text": "context window exceeded"}, "context_too_long"),
        ({"send_done": False}, "provider_error"),
        ({"first_chunk_delay": 2.0}, "provider_timeout"),
    ],
)
def test_broken_streams_map_to_codes(
    make_fake_ollama: MakeFake, change: dict[str, object], code: str
) -> None:
    fake = make_fake_ollama()
    for name, value in change.items():
        setattr(fake.behaviour, name, value)

    async def body(pool: OllamaPool) -> None:
        with pytest.raises(ChatError) as error:
            await collect(pool)
        assert error.value.code == code

    run_with_pool(endpoint(fake.url), body=body)


def test_redirects_are_never_followed(make_fake_ollama: MakeFake) -> None:
    fake, elsewhere = make_fake_ollama(), make_fake_ollama()
    fake.behaviour.redirect_to = f"{elsewhere.url}/api/chat"

    async def body(pool: OllamaPool) -> None:
        with pytest.raises(ChatError) as error:
            await collect(pool)
        assert error.value.code == "provider_error"

    run_with_pool(endpoint(fake.url), body=body)
    assert elsewhere.requests == []


def test_proxy_environment_is_ignored(
    make_fake_ollama: MakeFake, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake, proxy = make_fake_ollama(), make_fake_ollama()
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "all_proxy"):
        monkeypatch.setenv(name, proxy.url)

    async def body(pool: OllamaPool) -> None:
        assert await collect(pool) == "Hello from Ollama"

    run_with_pool(endpoint(fake.url), body=body)
    assert proxy.requests == []
    assert len(fake.chat_requests()) == 1


def test_status_is_cached_for_the_ttl(make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    now = [100.0]

    async def scenario() -> None:
        pool, client = make_pool(endpoint(fake.url), clock=lambda: now[0])
        async with client:
            [first] = await pool.status()
            assert first.reachable is True
            fake.behaviour.probe_status = 503
            now[0] += 5
            assert (await pool.status())[0].reachable is True
            now[0] += 6
            assert (await pool.status())[0].reachable is False

    run_async(scenario())


def test_stopping_the_consumer_closes_the_upstream_stream(make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    fake.behaviour.chunks = [f"w{i} " for i in range(30)]
    fake.behaviour.chunk_delay = 0.1

    async def body(pool: OllamaPool) -> None:
        provider = await pool.select()
        stream = cast(AsyncGenerator[str], provider.stream("SYSTEM", MESSAGES))
        assert await anext(stream) == "w0 "
        await stream.aclose()

    run_with_pool(endpoint(fake.url), body=body)
    assert fake.stream_closed_early.wait(timeout=3)
    assert not fake.stream_finished.is_set()

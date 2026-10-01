from collections.abc import Callable

import pytest

from ai_second_brain.chat.providers.base import ChatTimeouts
from ai_second_brain.chat.providers.ollama import create_http_client
from ai_second_brain.knowledge.embedder import Embedder, EmbedError

from ..conftest import run_async
from ..fakes.ollama import FakeOllama, fake_vector
from ..fakes.server import closed_port_url

FAST = ChatTimeouts(connect=1.0, read=0.5, probe=0.5)
MakeFake = Callable[[], FakeOllama]


def embed(url: str, texts: list[str], keep_alive: str | None = None) -> list[list[float]]:
    async def scenario() -> list[list[float]]:
        async with create_http_client() as client:
            embedder = Embedder(url, "bge-m3", 1024, client, FAST)
            if keep_alive is None:
                return await embedder.embed(texts)
            return await embedder.embed(texts, keep_alive=keep_alive)

    return run_async(scenario())


def test_embeds_batch_in_order(make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    vectors = embed(fake.url, ["a", "b"])
    assert vectors == [fake_vector("a"), fake_vector("b")]
    [request] = fake.embed_requests()
    assert request.body == {"model": "bge-m3", "input": ["a", "b"]}


def test_keep_alive_is_sent_when_set(make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    embed(fake.url, ["a"], keep_alive="30m")
    [request] = fake.embed_requests()
    assert request.body == {"model": "bge-m3", "input": ["a"], "keep_alive": "30m"}


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (
            {
                "embed_status": 404,
                "embed_error_text": 'model "bge-m3" not found, try pulling it first',
            },
            "embed_model_missing",
        ),
        ({"embed_status": 500}, "embed_unreachable"),
        ({"embed_dims": 512}, "embed_bad_response"),
        ({"embed_count_delta": -1}, "embed_bad_response"),
        ({"embed_nonfinite": True}, "embed_bad_response"),
        ({"embed_status": 400, "embed_error_text": "bad"}, "embed_bad_response"),
        ({"embed_raw_vector": [True] * 1024}, "embed_bad_response"),
        ({"embed_raw_vector": [10**400] * 1024}, "embed_bad_response"),
        ({"embed_status": 307}, "embed_bad_response"),
        ({"embed_delay": 2.0}, "embed_unreachable"),
    ],
)
def test_error_codes(make_fake_ollama: MakeFake, change: dict[str, object], code: str) -> None:
    fake = make_fake_ollama()
    for name, value in change.items():
        setattr(fake.behaviour, name, value)
    with pytest.raises(EmbedError) as error:
        embed(fake.url, ["a"])
    assert error.value.code == code


def test_unreachable_host() -> None:
    with pytest.raises(EmbedError) as error:
        embed(closed_port_url(), ["a"])
    assert error.value.code == "embed_unreachable"


def test_reachable(make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()

    async def scenario(url: str) -> bool:
        async with create_http_client() as client:
            return await Embedder(url, "bge-m3", 1024, client, FAST).reachable()

    assert run_async(scenario(fake.url)) is True
    assert run_async(scenario(closed_port_url())) is False

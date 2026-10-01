import asyncio

from ai_second_brain.knowledge.embedder import EmbedError
from ai_second_brain.runtime import new_event_loop
from ai_second_brain.search.embedding import QueryEmbedder, excerpt


class FakeEmbedder:
    def __init__(self, *, fail: bool = False, delay: float = 0.0) -> None:
        self.fail, self.delay, self.calls = fail, delay, 0
        self.keep_alive: list[str | None] = []

    async def embed(self, texts: list[str], *, keep_alive: str | None = None) -> list[list[float]]:
        self.calls += 1
        self.keep_alive.append(keep_alive)
        await asyncio.sleep(self.delay)
        if self.fail:
            raise EmbedError("embed_unreachable")
        return [[0.1] * 3]


def run(coro):  # type: ignore[no-untyped-def]
    loop = new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_returns_vector() -> None:
    assert run(QueryEmbedder(FakeEmbedder()).embed("q")) == [0.1] * 3  # type: ignore[arg-type]


def test_none_without_embedder() -> None:
    assert run(QueryEmbedder(None).embed("q")) is None


def test_breaker_skips_calls_for_cooldown() -> None:
    now = [100.0]
    fake = FakeEmbedder(fail=True)
    embedder = QueryEmbedder(fake, cooldown=30, clock=lambda: now[0])  # type: ignore[arg-type]
    assert run(embedder.embed("q")) is None and fake.calls == 1
    now[0] = 120.0
    assert run(embedder.embed("q")) is None and fake.calls == 1
    now[0] = 131.0
    fake.fail = False
    assert run(embedder.embed("q")) == [0.1] * 3 and fake.calls == 2


def test_timeout_counts_as_failure() -> None:
    fake = FakeEmbedder(delay=0.5)
    assert run(QueryEmbedder(fake, timeout=0.05).embed("q")) is None  # type: ignore[arg-type]


def test_timeout_opens_breaker_for_five_seconds_only() -> None:
    now = [100.0]
    fake = FakeEmbedder(delay=0.5)
    embedder = QueryEmbedder(fake, timeout=0.05, clock=lambda: now[0])  # type: ignore[arg-type]
    assert run(embedder.embed("q")) is None and fake.calls == 1
    now[0] = 104.0
    assert run(embedder.embed("q")) is None and fake.calls == 1
    now[0] = 105.5
    fake.delay = 0.0
    assert run(embedder.embed("q")) == [0.1] * 3 and fake.calls == 2


def test_embed_error_opens_breaker_for_thirty_seconds() -> None:
    now = [100.0]
    fake = FakeEmbedder(fail=True)
    embedder = QueryEmbedder(fake, clock=lambda: now[0])  # type: ignore[arg-type]
    assert run(embedder.embed("q")) is None and fake.calls == 1
    now[0] = 106.0
    assert run(embedder.embed("q")) is None and fake.calls == 1
    now[0] = 129.0
    assert run(embedder.embed("q")) is None and fake.calls == 1
    now[0] = 130.5
    fake.fail = False
    assert run(embedder.embed("q")) == [0.1] * 3 and fake.calls == 2


def test_per_call_timeout_override() -> None:
    fake = FakeEmbedder(delay=0.2)
    embedder = QueryEmbedder(fake, timeout=0.05)  # type: ignore[arg-type]
    assert run(embedder.embed("q", timeout=2.0)) == [0.1] * 3
    assert run(embedder.embed("q")) is None


def test_query_embeds_keep_the_model_loaded() -> None:
    fake = FakeEmbedder()
    run(QueryEmbedder(fake).embed("q"))  # type: ignore[arg-type]
    assert fake.keep_alive == ["30m"]


def test_excerpt_escapes_and_cuts_at_word() -> None:
    text = "<b>bold</b> & " + "word " * 100
    out = excerpt(text, 40)
    assert out.startswith("&lt;b&gt;bold&lt;/b&gt; &amp;") and len(out) <= 41 and out.endswith("…")


def test_excerpt_never_splits_an_entity() -> None:
    out = excerpt("<" * 300, 10)
    assert out.endswith("…")
    assert out[:-1].replace("&lt;", "") == ""

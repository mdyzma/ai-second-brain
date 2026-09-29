import asyncio
from collections.abc import AsyncIterator

from ai_second_brain.chat.events import DoneEvent, TokenEvent, TurnEvent
from ai_second_brain.interfaces.api.sse import sse_stream

from ..conftest import run_async


def test_frames_events_and_pings_while_waiting() -> None:
    async def events() -> AsyncIterator[TurnEvent]:
        await asyncio.sleep(0.25)
        yield TokenEvent(text="hi")
        yield DoneEvent()

    async def scenario() -> list[str]:
        return [chunk async for chunk in sse_stream(events(), ping_interval=0.1)]

    chunks = run_async(scenario())
    assert chunks[0] == ": ping\n\n"
    assert chunks[-2].startswith("event: token\n")
    assert chunks[-1].startswith("event: done\n")


def test_closing_the_stream_cancels_the_turn() -> None:
    finished: list[str] = []

    async def events() -> AsyncIterator[TurnEvent]:
        try:
            yield TokenEvent(text="first")
            await asyncio.sleep(10)
            yield DoneEvent()
        finally:
            finished.append("cleanup ran")

    async def scenario() -> None:
        stream = sse_stream(events(), ping_interval=5)
        assert (await anext(stream)).startswith("event: token")
        await stream.aclose()

    run_async(scenario())
    assert finished == ["cleanup ran"]

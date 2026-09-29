"""Server-Sent Events framing for chat turns.

The turn runs in one pump task (so the HTTP client's streams stay in one task). The response
generator reads from a queue and emits a `: ping` comment whenever nothing arrived for
`ping_interval` seconds. Closing the response (client disconnect, Stop) cancels the pump,
which cancels the provider request.
"""

import asyncio
import contextlib
from collections.abc import AsyncGenerator, AsyncIterator

from ai_second_brain.chat.events import PING, TurnEvent, encode_sse


async def sse_stream(
    events: AsyncIterator[TurnEvent], ping_interval: float
) -> AsyncGenerator[str, None]:
    queue: asyncio.Queue[TurnEvent | None] = asyncio.Queue()

    async def pump() -> None:
        try:
            async for event in events:
                queue.put_nowait(event)
        finally:
            queue.put_nowait(None)

    task = asyncio.create_task(pump())
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=ping_interval)
            except TimeoutError:
                yield PING
                continue
            if event is None:
                break
            yield encode_sse(event)
        await task
    finally:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

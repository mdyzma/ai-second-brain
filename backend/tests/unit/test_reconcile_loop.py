import asyncio
from types import SimpleNamespace
from typing import Any, cast

from ai_second_brain.ingest.worker import _reconcile_loop  # pyright: ignore[reportPrivateUsage]
from ai_second_brain.runtime import new_event_loop


def test_wake_triggers_reconcile_and_errors_do_not_kill_loop() -> None:
    triggers: list[str] = []

    async def fake(ctx: Any, *, trigger: str) -> None:
        triggers.append(trigger)
        if trigger == "startup":
            raise RuntimeError("boom")

    async def scenario() -> None:
        ctx = cast(Any, SimpleNamespace(settings=SimpleNamespace(reconcile_minutes=60)))
        stop, wake = asyncio.Event(), asyncio.Event()
        task = asyncio.create_task(_reconcile_loop(ctx, stop, wake, fake))
        await asyncio.sleep(0.1)
        wake.set()
        await asyncio.sleep(0.1)
        stop.set()
        await asyncio.wait_for(task, 5)

    loop = new_event_loop()
    try:
        loop.run_until_complete(scenario())
    finally:
        loop.close()
    assert triggers == ["startup", "schedule"]

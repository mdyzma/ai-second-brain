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
        task = asyncio.create_task(_reconcile_loop(ctx, stop, wake, fake, wake_interval=0))
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


def test_wakes_are_coalesced_to_one_reconcile_per_interval() -> None:
    triggers: list[str] = []

    async def fake(ctx: Any, *, trigger: str) -> None:
        triggers.append(trigger)

    async def scenario() -> list[str]:
        ctx = cast(Any, SimpleNamespace(settings=SimpleNamespace(reconcile_minutes=60)))
        stop, wake = asyncio.Event(), asyncio.Event()
        task = asyncio.create_task(_reconcile_loop(ctx, stop, wake, fake, wake_interval=0.5))
        for _ in range(8):  # a burst of saves inside one interval
            await asyncio.sleep(0.04)
            wake.set()
        during = list(triggers)
        await asyncio.sleep(0.8)  # the deadline passes: the coalesced wake still runs
        stop.set()
        await asyncio.wait_for(task, 5)
        return during

    loop = new_event_loop()
    try:
        during = loop.run_until_complete(scenario())
    finally:
        loop.close()
    assert during == ["startup"]
    assert triggers == ["startup", "schedule"]

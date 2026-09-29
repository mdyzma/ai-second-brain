import asyncio

from ai_second_brain.runtime import new_event_loop


def test_new_event_loop_is_a_selector_loop() -> None:
    loop = new_event_loop()
    try:
        assert isinstance(loop, asyncio.SelectorEventLoop)
    finally:
        loop.close()

"""Event loop factory for uvicorn (`loop="ai_second_brain.runtime:new_event_loop"`).

psycopg's async mode needs a selector event loop. On Windows, asyncio and uvicorn otherwise
use the Proactor loop. macOS and Linux already default to selector loops.
"""

import asyncio


def new_event_loop() -> asyncio.AbstractEventLoop:
    return asyncio.SelectorEventLoop()

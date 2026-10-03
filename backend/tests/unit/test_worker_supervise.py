import asyncio
import logging
from typing import Any

import pytest
from psycopg_pool import PoolTimeout

from ai_second_brain.config import Settings
from ai_second_brain.ingest import worker
from ai_second_brain.runtime import new_event_loop

from ..conftest import TEST_HASH


def run(coro: Any) -> Any:
    loop = new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_supervisor_restarts_a_worker_that_exits(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="ai_second_brain.ingest")
    calls: list[int] = []

    async def scenario() -> None:
        stop = asyncio.Event()

        async def run_once() -> None:
            calls.append(1)
            if len(calls) == 1:
                raise ConnectionError("heartbeat lost")  # Postgres restarted
            stop.set()
            await asyncio.Event().wait()  # blocks until cancelled

        await asyncio.wait_for(worker._supervise(run_once, stop), 10)  # pyright: ignore[reportPrivateUsage]

    run(scenario())
    assert len(calls) == 2
    assert "database_unavailable type=ConnectionError" in caplog.text


class _DownPool:
    opened = 0

    def __init__(self, url: str) -> None:
        self.url = url

    async def open(self, wait: bool, timeout: float) -> None:  # noqa: ASYNC109
        _DownPool.opened += 1
        raise PoolTimeout(f"pool initialization incomplete for {self.url}")

    async def close(self) -> None:
        return None


def test_startup_retries_an_unreachable_database_until_stopped(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="ai_second_brain.ingest")
    monkeypatch.setattr(worker, "create_pool", _DownPool)
    values: dict[str, Any] = {
        "DATABASE_URL": "postgresql://nobody:x@db.example/nothing",
        "owner_password_hash": TEST_HASH,
        "vault_path": None,
    }
    settings = Settings(_env_file=None, **values)  # pyright: ignore[reportCallIssue]

    async def scenario() -> int:
        stop = asyncio.Event()
        asyncio.get_running_loop().call_later(1.5, stop.set)  # during the 2nd backoff wait
        return await asyncio.wait_for(worker.run_worker(settings, stop_event=stop), 10)

    assert run(scenario()) == 0
    assert _DownPool.opened == 2  # tried at 0 s and 1 s, then stopped mid-backoff
    assert caplog.text.count("database_unavailable type=PoolTimeout") == 2
    assert "nobody" not in caplog.text and "db.example" not in caplog.text


class _FakeApp:
    """Records each run_worker_async call; `extract_crashes` makes the first extract run fail."""

    def __init__(self, stop: asyncio.Event, extract_crashes: int = 0) -> None:
        self.runs: list[dict[str, Any]] = []
        self.stop, self.crashes = stop, extract_crashes
        self.running: set[tuple[str, ...]] = set()
        self.cancelled: list[tuple[str, ...]] = []

    async def run_worker_async(self, **kwargs: Any) -> None:
        queues = tuple(kwargs["queues"])
        self.runs.append(kwargs)
        if queues == ("extract",) and self.crashes > 0:
            self.crashes -= 1
            raise ConnectionError("heartbeat lost")
        self.running.add(queues)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.append(queues)
            raise
        finally:
            self.running.discard(queues)


def test_extraction_runs_in_its_own_loop_and_both_stop_on_shutdown() -> None:
    async def scenario() -> None:
        stop = asyncio.Event()
        app = _FakeApp(stop)
        tasks = worker.start_job_loops(app, "ingest-ctx", "graph-ctx", stop)  # pyright: ignore[reportArgumentType]
        await asyncio.sleep(0.1)
        assert app.running == {("ingest", "embed"), ("extract",)}
        by_queue = {tuple(r["queues"]): r for r in app.runs}
        assert by_queue[("ingest", "embed")]["concurrency"] == 2
        assert by_queue[("extract",)]["concurrency"] == 1
        for run_args in app.runs:
            assert run_args["additional_context"] == {"ingest": "ingest-ctx", "graph": "graph-ctx"}
        stop.set()
        await asyncio.wait_for(asyncio.gather(*tasks), 5)
        assert app.running == set()
        assert set(app.cancelled) == {("ingest", "embed"), ("extract",)}

    run(scenario())


def test_crashed_extract_loop_restarts_while_ingest_keeps_running() -> None:
    async def scenario() -> None:
        stop = asyncio.Event()
        app = _FakeApp(stop, extract_crashes=1)
        tasks = worker.start_job_loops(app, "i", "g", stop)  # pyright: ignore[reportArgumentType]
        await asyncio.sleep(0.1)
        assert app.running == {("ingest", "embed")}  # extract is backing off (1 s)
        await asyncio.sleep(1.3)
        assert app.running == {("ingest", "embed"), ("extract",)}
        ingest_runs = [r for r in app.runs if tuple(r["queues"]) == ("ingest", "embed")]
        assert len(ingest_runs) == 1  # never restarted
        stop.set()
        await asyncio.wait_for(asyncio.gather(*tasks), 5)

    run(scenario())

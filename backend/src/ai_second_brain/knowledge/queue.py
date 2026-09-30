"""Deferring ingest jobs. procrastinate uses its own connection, so jobs are deferred right after
the data commits; reconcile re-queues anything lost in between (plan ruling 1)."""

from typing import Protocol
from uuid import UUID

from procrastinate import App
from procrastinate.exceptions import AlreadyEnqueued, UniqueViolation
from procrastinate.types import JSONValue


class JobQueue(Protocol):
    async def index_source(self, source_id: UUID) -> None: ...
    async def embed_revision(self, revision_id: UUID, space_id: int) -> None: ...
    async def reconcile(self, run_id: int) -> None: ...
    async def reset_stalled(self, seconds_since_heartbeat: int) -> int: ...


class ProcrastinateQueue:
    def __init__(self, app: App) -> None:
        self._app = app

    async def _defer(self, task: str, lock: str | None, **kwargs: JSONValue) -> None:
        try:
            await self._app.configure_task(task, queueing_lock=lock).defer_async(**kwargs)
        except AlreadyEnqueued:
            pass

    async def index_source(self, source_id: UUID) -> None:
        await self._defer("ingest:index_source", f"index:{source_id}", source_id=str(source_id))

    async def embed_revision(self, revision_id: UUID, space_id: int) -> None:
        await self._defer(
            "ingest:embed_revision",
            f"embed:{revision_id}",
            revision_id=str(revision_id),
            space_id=space_id,
        )

    async def reconcile(self, run_id: int) -> None:
        await self._defer("ingest:reconcile_vault", "reconcile", run_id=run_id)

    async def reset_stalled(self, seconds_since_heartbeat: int) -> int:
        stalled = await self._app.job_manager.get_stalled_jobs(
            seconds_since_heartbeat=seconds_since_heartbeat
        )
        count = 0
        for job in stalled:
            try:
                await self._app.job_manager.retry_job(job)
            except UniqueViolation:  # a twin with the same queueing lock is already waiting
                continue
            count += 1
        return count

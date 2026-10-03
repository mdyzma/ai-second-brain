"""procrastinate job app. Job arguments are ids only; never note text, titles or paths."""

import copy
from typing import TYPE_CHECKING, Any
from uuid import UUID

from procrastinate import (
    App,
    BaseRetryStrategy,
    Blueprint,
    JobContext,
    PsycopgConnector,
    RetryDecision,
)
from procrastinate.jobs import Job
from psycopg_pool import AsyncConnectionPool

from ai_second_brain.knowledge.embedder import EMBED_RETRY_SECONDS, EmbedRetryable

if TYPE_CHECKING:
    from ai_second_brain.graph.context import GraphContext
    from ai_second_brain.knowledge.context import IngestContext

INGEST_QUEUE = "ingest"
EMBED_QUEUE = "embed"
EXTRACT_QUEUE = "extract"

blueprint = Blueprint()


INDEX_RETRY_SECONDS = (10, 30, 90)


class ScheduleRetry(BaseRetryStrategy):
    """Retry on the listed delays (seconds), optionally only for some exception types."""

    def __init__(
        self, schedule: tuple[int, ...], only: tuple[type[BaseException], ...] = ()
    ) -> None:
        self.schedule, self.only = schedule, only

    def get_retry_decision(self, *, exception: BaseException, job: Job) -> RetryDecision | None:
        if self.only and not isinstance(exception, self.only):
            return None
        if job.attempts >= len(self.schedule):
            return None
        return RetryDecision(retry_in={"seconds": self.schedule[job.attempts]})


def _ctx(context: JobContext) -> "IngestContext":
    return context.additional_context["ingest"]


def _graph(context: JobContext) -> "GraphContext":
    return context.additional_context["graph"]


@blueprint.task(
    name="index_source",
    queue=INGEST_QUEUE,
    pass_context=True,
    retry=ScheduleRetry(INDEX_RETRY_SECONDS),
)
async def index_source_task(context: JobContext, source_id: str) -> None:
    from ai_second_brain.knowledge import store
    from ai_second_brain.knowledge.index import index_source

    ctx = _ctx(context)
    try:
        await index_source(ctx, UUID(source_id))
    except Exception:
        if context.job.attempts >= len(INDEX_RETRY_SECONDS):
            async with ctx.pool.connection() as conn:
                await store.mark_index_failed(conn, UUID(source_id))
        raise


@blueprint.task(
    name="embed_revision",
    queue=EMBED_QUEUE,
    pass_context=True,
    retry=ScheduleRetry(EMBED_RETRY_SECONDS, only=(EmbedRetryable,)),
)
async def embed_revision_task(context: JobContext, revision_id: str, space_id: int) -> None:
    from ai_second_brain.knowledge.embed import embed_revision

    await embed_revision(_ctx(context), UUID(revision_id), space_id)


# Unreachable model or a database conflict: retried on the first five embed delays.
EXTRACT_RETRY_SECONDS = EMBED_RETRY_SECONDS[:5]


class _ExtractRetry(ScheduleRetry):
    """Reads the module constant per call, so tests can shorten the schedule."""

    def get_retry_decision(self, *, exception: BaseException, job: Job) -> RetryDecision | None:
        self.schedule = EXTRACT_RETRY_SECONDS
        return super().get_retry_decision(exception=exception, job=job)


def _extract_retryable() -> tuple[type[BaseException], ...]:
    from psycopg.errors import DeadlockDetected, SerializationFailure

    from ai_second_brain.graph.llm import ExtractUnreachable

    return (ExtractUnreachable, DeadlockDetected, SerializationFailure)


@blueprint.task(
    name="graph_extract_revision",
    queue=EXTRACT_QUEUE,
    pass_context=True,
    retry=_ExtractRetry(EXTRACT_RETRY_SECONDS, only=_extract_retryable()),
)
async def graph_extract_revision_task(context: JobContext, revision_id: str) -> None:
    from psycopg.errors import DeadlockDetected, SerializationFailure

    from ai_second_brain.graph.extract import extract_revision, mark_failed
    from ai_second_brain.graph.llm import ExtractUnreachable

    ctx = _graph(context)
    try:
        await extract_revision(ctx, UUID(revision_id))
    except (ExtractUnreachable, DeadlockDetected, SerializationFailure) as error:
        if context.job.attempts < len(EXTRACT_RETRY_SECONDS):
            raise  # the retry strategy reschedules it
        # Out of retries: record it (a failed row is re-queued only by "Retry failed") and end
        # normally. A database conflict that outlasts every retry is reported as its own code.
        unreachable = isinstance(error, ExtractUnreachable)
        code = "extract_unreachable" if unreachable else "extract_db_conflict"
        await mark_failed(ctx, UUID(revision_id), code)
    # Any other exception propagates and fails the job without an extractions row: the revision
    # stays pending, so the next `graph extract` queues it again.


@blueprint.task(
    name="graph_embed_entity",
    queue=EMBED_QUEUE,
    pass_context=True,
    retry=ScheduleRetry(EMBED_RETRY_SECONDS, only=(EmbedRetryable,)),
)
async def graph_embed_entity_task(context: JobContext, entity_id: str) -> None:
    from ai_second_brain.graph.embed import embed_entity

    await embed_entity(_ctx(context), UUID(entity_id))


@blueprint.task(name="reconcile_vault", queue=INGEST_QUEUE, pass_context=True)
async def reconcile_vault_task(context: JobContext, run_id: int) -> None:
    from ai_second_brain.vault.reconcile import reconcile

    await reconcile(_ctx(context), trigger="manual", run_id=run_id)


class _QuickOpenPool(AsyncConnectionPool):
    """procrastinate opens its pool with wait=True and a 30 s default; cap the wait."""

    def __init__(self, *args: Any, open_timeout: float, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._open_timeout = open_timeout

    async def open(self, wait: bool = False, timeout: float = 30.0) -> None:  # noqa: ASYNC109
        await super().open(wait=wait, timeout=self._open_timeout)

    async def close(self, timeout: float = 5.0) -> None:  # noqa: ASYNC109
        await super().close(timeout=min(timeout, 0.5))  # workers stuck connecting shouldn't stall


def create_job_app(database_url: str, *, open_timeout: float | None = None) -> App:
    options: dict[str, Any] = {}
    if open_timeout is not None:

        def pool_factory(**kwargs: Any) -> AsyncConnectionPool:
            return _QuickOpenPool(open_timeout=open_timeout, **kwargs)

        options["pool_factory"] = pool_factory
    app = App(connector=PsycopgConnector(conninfo=database_url, **options))
    # add_tasks_from renames and rebinds the tasks it copies, so hand each app its own copy
    app.add_tasks_from(copy.deepcopy(blueprint), namespace="ingest")
    return app

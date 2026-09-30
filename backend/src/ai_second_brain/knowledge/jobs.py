"""procrastinate job app. Job arguments are ids only; never note text, titles or paths."""

import copy
from typing import TYPE_CHECKING
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

from ai_second_brain.knowledge.embedder import EMBED_RETRY_SECONDS, EmbedRetryable

if TYPE_CHECKING:
    from ai_second_brain.knowledge.context import IngestContext

INGEST_QUEUE = "ingest"
EMBED_QUEUE = "embed"

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


@blueprint.task(name="reconcile_vault", queue=INGEST_QUEUE, pass_context=True)
async def reconcile_vault_task(context: JobContext, run_id: int) -> None:
    from ai_second_brain.vault.reconcile import reconcile

    await reconcile(_ctx(context), trigger="manual", run_id=run_id)


def create_job_app(database_url: str) -> App:
    app = App(connector=PsycopgConnector(conninfo=database_url))
    # add_tasks_from renames and rebinds the tasks it copies, so hand each app its own copy
    app.add_tasks_from(copy.deepcopy(blueprint), namespace="ingest")
    return app

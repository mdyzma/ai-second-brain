"""procrastinate job app. Job arguments are ids only; never note text, titles or paths."""

from procrastinate import App, Blueprint, JobContext, PsycopgConnector

INGEST_QUEUE = "ingest"
EMBED_QUEUE = "embed"

blueprint = Blueprint()


@blueprint.task(name="index_source", queue=INGEST_QUEUE, pass_context=True)
async def index_source_task(context: JobContext, source_id: str) -> None:
    raise NotImplementedError  # Task 6


@blueprint.task(name="embed_revision", queue=EMBED_QUEUE, pass_context=True)
async def embed_revision_task(context: JobContext, revision_id: str, space_id: int) -> None:
    raise NotImplementedError  # Task 7


@blueprint.task(name="reconcile_vault", queue=INGEST_QUEUE, pass_context=True)
async def reconcile_vault_task(context: JobContext, run_id: int) -> None:
    raise NotImplementedError  # Task 8


def create_job_app(database_url: str) -> App:
    app = App(connector=PsycopgConnector(conninfo=database_url))
    app.add_tasks_from(blueprint, namespace="ingest")
    return app

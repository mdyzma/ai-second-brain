import logging
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from ai_second_brain.interfaces.api.deps import get_settings, require_same_origin, require_session
from ai_second_brain.interfaces.api.schemas import (
    ErrorResponse,
    ReconcileQueued,
    SourceList,
    SourcesSummary,
)
from ai_second_brain.knowledge import status as read
from ai_second_brain.knowledge import store
from ai_second_brain.knowledge.queue import JobQueue

logger = logging.getLogger("ai_second_brain.api")

router = APIRouter(tags=["sources"], dependencies=[Depends(require_session)])
ERRORS: dict[int | str, dict[str, Any]] = {
    k: {"model": ErrorResponse} for k in (401, 403, 422, 503)
}


def _queue(request: Request) -> JobQueue:
    queue = request.app.state.ingest.queue
    if queue is None:  # the job app could not open at startup
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="database_unavailable")
    return queue


@router.get(
    "/sources/summary",
    operation_id="sourcesSummary",
    response_model=SourcesSummary,
    responses=ERRORS,
)
async def sources_summary(request: Request) -> Any:
    ingest = request.app.state.ingest
    reachable = await ingest.host_reachable()
    async with request.app.state.pool.connection() as conn:
        return await read.summary(conn, get_settings(request), ingest.space_id, reachable)


@router.get("/sources", operation_id="listSources", response_model=SourceList, responses=ERRORS)
async def list_sources(
    request: Request,
    state: Literal["pending", "indexed", "failed", "deleted"] | None = None,
    q: str | None = Query(default=None, max_length=200),
    cursor: str | None = Query(default=None, max_length=500),
) -> Any:
    async with request.app.state.pool.connection() as conn:
        return await read.list_sources(
            conn, request.app.state.ingest.space_id, state=state, q=q, cursor=cursor
        )


@router.post(
    "/sources/{source_id}/retry",
    operation_id="retrySource",
    status_code=status.HTTP_202_ACCEPTED,
    response_class=Response,
    dependencies=[Depends(require_same_origin)],
    responses={**ERRORS, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def retry_source(source_id: UUID, request: Request) -> None:
    ingest = request.app.state.ingest
    queue = _queue(request)
    async with request.app.state.pool.connection() as conn:
        kind, revision_id = await read.retry_source(conn, source_id, ingest.space_id)
    if kind == "missing":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not_found")
    if kind == "none":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="nothing_to_retry")
    try:
        if kind == "index":
            await queue.index_source(source_id)
        elif revision_id is not None:
            await queue.embed_revision(revision_id, ingest.space_id)
    except Exception as error:  # reconcile re-queues whatever was lost
        logger.warning("retry_queue_error type=%s", type(error).__name__)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail="database_unavailable"
        ) from error


@router.post(
    "/sources/reconcile",
    operation_id="reconcileVault",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ReconcileQueued,
    dependencies=[Depends(require_same_origin)],
    responses={**ERRORS, 409: {"model": ErrorResponse}},
)
async def reconcile_vault(request: Request) -> ReconcileQueued:
    if get_settings(request).vault_path is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="vault_disabled")
    queue = _queue(request)
    pool = request.app.state.pool
    async with pool.connection() as conn:
        run_id = await store.start_run(conn, "manual")
    try:
        await queue.reconcile(run_id)
    except Exception as error:
        logger.warning("reconcile_queue_error type=%s", type(error).__name__)
        async with pool.connection() as conn:  # never leave an orphaned 'running' row
            await store.finish_run(conn, run_id, "error:queue_unavailable", {})
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail="database_unavailable"
        ) from error
    return ReconcileQueued(run_id=run_id)

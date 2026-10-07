"""Nightly routes (spec §7): the morning digest, the run list, a manual start."""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ai_second_brain.interfaces.api.deps import get_settings, require_same_origin, require_session
from ai_second_brain.interfaces.api.schemas import (
    Digest,
    ErrorResponse,
    NightlyRunList,
    NightlyStarted,
)
from ai_second_brain.nightly import digest as digests
from ai_second_brain.nightly.run import close_open_run, start_run

router = APIRouter(tags=["nightly"], dependencies=[Depends(require_session)])
ERRORS: dict[int | str, dict[str, Any]] = {
    k: {"model": ErrorResponse} for k in (401, 403, 422, 503)
}


def _digest_body(request: Request, body: dict[str, Any] | None) -> dict[str, Any]:
    """The digest plus the settings the no-runs copy needs; null sections without a run."""
    settings = get_settings(request)
    return {
        "nightly_at": settings.nightly_at,
        "nightly_enabled": settings.nightly_enabled,
        "run": None,
        "review": None,
        "failed": None,
        "indexed": None,
        **(body or {}),
    }


async def _close_drained(request: Request) -> None:
    """Close-on-read: a run whose jobs have drained reads as complete at once, not at the next
    15-minute tick. Stateless, and guarded against runs still queueing (`close_open_run`)."""
    await close_open_run(request.app.state.pool, get_settings(request))


@router.get("/digest", operation_id="getDigest", response_model=Digest, responses=ERRORS)
async def get_digest(request: Request) -> Any:
    await _close_drained(request)
    async with request.app.state.pool.connection() as conn:
        run_id = await digests.latest_run_id(conn)
        body = None if run_id is None else await digests.digest(conn, run_id)
    return _digest_body(request, body)


@router.get(
    "/digest/{run_date}",
    operation_id="getDigestByDate",
    response_model=Digest,
    responses={**ERRORS, 404: {"model": ErrorResponse}},
)
async def get_digest_by_date(run_date: date, request: Request) -> Any:
    await _close_drained(request)
    async with request.app.state.pool.connection() as conn:
        run_id = await digests.run_id_for_date(conn, run_date)
        body = None if run_id is None else await digests.digest(conn, run_id)
    if body is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not_found")
    return _digest_body(request, body)


@router.get(
    "/nightly/runs", operation_id="listNightlyRuns", response_model=NightlyRunList, responses=ERRORS
)
async def list_nightly_runs(
    request: Request, limit: Annotated[int, Query(ge=1, le=365)] = 30
) -> Any:
    async with request.app.state.pool.connection() as conn:
        runs = await digests.list_runs(conn, limit)
    return {"runs": runs}


@router.post(
    "/nightly/run",
    operation_id="startNightlyRun",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=NightlyStarted,
    dependencies=[Depends(require_same_origin)],
    responses={**ERRORS, 409: {"model": ErrorResponse}},
)
async def start_nightly_run(request: Request) -> Any:
    queue = await request.app.state.ingest.get_queue()
    if queue is None:  # the job app can't open: the database is down
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="database_unavailable")
    pool = request.app.state.pool
    result = await start_run(pool, queue, get_settings(request), "manual")
    if result.outcome == "busy":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="nightly_busy")
    if result.outcome == "failed" or result.run_id is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="nightly_failed")
    async with pool.connection() as conn:
        body = await digests.digest(conn, result.run_id)
    if body is None:  # the row was just written
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="nightly_failed")
    return {"run": body["run"]}

import logging
from typing import Any

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from psycopg_pool import PoolTimeout
from starlette.concurrency import run_in_threadpool

from ai_second_brain.auth.passwords import verify_password
from ai_second_brain.auth.sessions import Session
from ai_second_brain.interfaces.api.deps import (
    SESSION_COOKIE,
    clear_session_cookie,
    get_settings,
    get_store,
    require_same_origin,
    require_session,
    set_session_cookie,
)
from ai_second_brain.interfaces.api.schemas import ErrorResponse, LoginRequest, MeResponse

logger = logging.getLogger("ai_second_brain.api")
router = APIRouter(tags=["auth"])

ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}


@router.post(
    "/login",
    operation_id="login",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    dependencies=[Depends(require_same_origin)],
    responses={**ERRORS, 429: {"model": ErrorResponse}},
)
async def login(body: LoginRequest, request: Request, response: Response) -> None:
    settings = get_settings(request)
    throttle = request.app.state.throttle
    # One login at a time: otherwise parallel requests all pass retry_after()
    # before the first failure is recorded, bypassing the throttle.
    async with request.app.state.login_lock:
        wait = throttle.retry_after()
        if wait is not None:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail="too_many_attempts",
                headers={"Retry-After": str(wait)},
            )
        # argon2 is CPU-heavy; keep it off the event loop.
        if not await run_in_threadpool(
            verify_password, settings.owner_password_hash, body.password
        ):
            throttle.record_failure()
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials")
        throttle.record_success()
        token = await get_store(request).create(request.headers.get("user-agent"))
    set_session_cookie(response, token, settings)


@router.post(
    "/logout",
    operation_id="logout",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    dependencies=[Depends(require_same_origin)],
    responses=ERRORS,
)
async def logout(request: Request, response: Response) -> Response | None:
    settings = get_settings(request)
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        try:
            await get_store(request).revoke(token)
        except (PoolTimeout, psycopg.OperationalError):
            # The session row may survive, but the browser must still drop its cookie.
            # A handler-built 503 would lose headers set on `response`, so build it here.
            logger.warning("logout: session not revoked, database unavailable")
            failure = JSONResponse(status_code=503, content={"detail": "database_unavailable"})
            clear_session_cookie(failure, settings)
            return failure
    clear_session_cookie(response, settings)
    return None


@router.get("/me", operation_id="me", response_model=MeResponse, responses=ERRORS)
async def me(session: Session = Depends(require_session)) -> MeResponse:  # noqa: B008
    return MeResponse(authenticated=True, expires_at=session.expires_at)

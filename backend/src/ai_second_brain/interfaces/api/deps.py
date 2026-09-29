"""Request dependencies: CSRF origin check, session resolution, cookie helpers."""

from fastapi import Depends, HTTPException, Request, Response, status

from ai_second_brain.auth.sessions import Session, SessionStore
from ai_second_brain.config import Settings

SESSION_COOKIE = "sb_session"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def is_same_origin(
    method: str, sec_fetch_site: str | None, origin: str | None, allowed: frozenset[str]
) -> bool:
    if method.upper() not in UNSAFE_METHODS:
        return True
    if sec_fetch_site == "same-origin":
        return True
    return origin is not None and origin.rstrip("/") in allowed


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_store(request: Request) -> SessionStore:
    return request.app.state.sessions


async def require_same_origin(request: Request) -> None:
    allowed = get_settings(request).allowed_origin_set
    if not is_same_origin(
        request.method,
        request.headers.get("sec-fetch-site"),
        request.headers.get("origin"),
        allowed,
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="cross_origin")


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_days * 24 * 3600,
        path="/api",
        httponly=True,
        samesite="strict",
        secure=settings.cookie_secure,
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        SESSION_COOKIE, path="/api", httponly=True, samesite="strict", secure=settings.cookie_secure
    )


async def optional_session(request: Request, response: Response) -> Session | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    store = get_store(request)
    session = await store.get(token)
    if session is None:
        return None
    touched = await store.touch(session)
    if touched is not session:
        set_session_cookie(response, token, get_settings(request))
    return touched


async def require_session(session: Session | None = Depends(optional_session)) -> Session:  # noqa: B008
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="not_authenticated")
    return session

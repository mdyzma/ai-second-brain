"""Server-side sessions. Only sha256(token) is stored; the raw token lives in the cookie."""

import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from psycopg_pool import AsyncConnectionPool

TOUCH_INTERVAL = timedelta(minutes=5)
MAX_TOKEN_LENGTH = 256


@dataclass(frozen=True, slots=True)
class Session:
    id: bytes
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime


def token_id(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


class SessionStore:
    def __init__(
        self, pool: AsyncConnectionPool, ttl: timedelta, clock: Callable[[], datetime]
    ) -> None:
        self._pool = pool
        self._ttl = ttl
        self._clock = clock

    async def create(self, user_agent: str | None) -> str:
        token = secrets.token_urlsafe(32)
        now = self._clock()
        agent = (user_agent or "")[:512] or None
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO auth_sessions (id, created_at, last_seen_at, expires_at, user_agent)"
                " VALUES (%s, %s, %s, %s, %s)",
                (token_id(token), now, now, now + self._ttl, agent),
            )
        return token

    async def get(self, token: str) -> Session | None:
        if not token or len(token) > MAX_TOKEN_LENGTH:
            return None
        async with self._pool.connection() as conn:
            cursor = await conn.execute(
                "SELECT id, created_at, last_seen_at, expires_at FROM auth_sessions"
                " WHERE id = %s AND expires_at > %s",
                (token_id(token), self._clock()),
            )
            row = await cursor.fetchone()
        return Session(*row) if row else None

    async def touch(self, session: Session) -> Session:
        """Slide the expiry forward, writing at most once per TOUCH_INTERVAL."""
        now = self._clock()
        if now - session.last_seen_at < TOUCH_INTERVAL:
            return session
        expires_at = now + self._ttl
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE auth_sessions SET last_seen_at = %s, expires_at = %s WHERE id = %s",
                (now, expires_at, session.id),
            )
        return replace(session, last_seen_at=now, expires_at=expires_at)

    async def revoke(self, token: str) -> None:
        if not token or len(token) > MAX_TOKEN_LENGTH:
            return
        async with self._pool.connection() as conn:
            await conn.execute("DELETE FROM auth_sessions WHERE id = %s", (token_id(token),))

    async def purge_expired(self) -> int:
        async with self._pool.connection(timeout=2.0) as conn:
            cursor = await conn.execute(
                "DELETE FROM auth_sessions WHERE expires_at <= %s", (self._clock(),)
            )
            return cursor.rowcount

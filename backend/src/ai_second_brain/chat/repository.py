"""Chat sessions and turns. Turns are written only for successful answers."""

from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from ai_second_brain.chat.models import (
    TITLE_LENGTH,
    ChatMode,
    ChatSession,
    Source,
    Turn,
    TurnDraft,
    utc_now,
)


class SessionNotFoundError(Exception):
    """The session disappeared (for example deleted while a turn was streaming)."""


STORAGE_ERRORS: tuple[type[BaseException], ...] = (
    psycopg.Error,
    PoolTimeout,
    OSError,
    SessionNotFoundError,
)


class ChatRepository(Protocol):
    async def create_session(self, mode: ChatMode) -> ChatSession: ...
    async def list_sessions(self) -> list[ChatSession]: ...
    async def get_session(self, session_id: UUID) -> ChatSession | None: ...
    async def delete_session(self, session_id: UUID) -> bool: ...
    async def list_turns(self, session_id: UUID) -> list[Turn]: ...
    async def recent_turns(self, session_id: UUID, limit: int) -> list[Turn]: ...
    async def save_turn(self, session_id: UUID, draft: TurnDraft) -> Turn: ...


class InMemoryChatRepository:
    """Process-local repository: unit tests and `chat-smoke` (which must save nothing)."""

    def __init__(self, clock: Callable[[], datetime] = utc_now) -> None:
        self._clock = clock
        self._sessions: dict[UUID, ChatSession] = {}
        self._turns: dict[UUID, list[Turn]] = {}

    async def create_session(self, mode: ChatMode) -> ChatSession:
        now = self._clock()
        session = ChatSession(id=uuid4(), mode=mode, title=None, created_at=now, updated_at=now)
        self._sessions[session.id] = session
        self._turns[session.id] = []
        return session

    async def list_sessions(self) -> list[ChatSession]:
        return sorted(
            self._sessions.values(), key=lambda s: (s.updated_at, s.created_at), reverse=True
        )

    async def get_session(self, session_id: UUID) -> ChatSession | None:
        return self._sessions.get(session_id)

    async def delete_session(self, session_id: UUID) -> bool:
        self._turns.pop(session_id, None)
        return self._sessions.pop(session_id, None) is not None

    async def list_turns(self, session_id: UUID) -> list[Turn]:
        return list(self._turns.get(session_id, []))

    async def recent_turns(self, session_id: UUID, limit: int) -> list[Turn]:
        return list(self._turns.get(session_id, []))[-limit:]

    async def save_turn(self, session_id: UUID, draft: TurnDraft) -> Turn:
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError
        turns = self._turns[session_id]
        turn = Turn(id=uuid4(), seq=len(turns) + 1, **_draft_fields(draft))
        turns.append(turn)
        self._sessions[session_id] = session.model_copy(
            update={
                "title": session.title or draft.question[:TITLE_LENGTH],
                "updated_at": draft.finished_at,
            }
        )
        return turn


def _draft_fields(draft: TurnDraft) -> dict[str, Any]:
    return {
        "question": draft.question,
        "answer": draft.answer,
        "sources": list(draft.sources),
        "endpoint": draft.endpoint,
        "model": draft.model,
        "degraded": draft.degraded,
        "started_at": draft.started_at,
        "finished_at": draft.finished_at,
    }


SESSION_COLUMNS = "id, mode, title, created_at, updated_at"
TURN_COLUMNS = (
    "id, seq, question, answer, sources, endpoint, model, degraded, started_at, finished_at"
)


def _session(row: dict[str, Any]) -> ChatSession:
    return ChatSession.model_validate(row)


def _turn(row: dict[str, Any]) -> Turn:
    sources = [Source.model_validate(item) for item in row["sources"]]
    return Turn.model_validate({**row, "sources": sources})


class PgChatRepository:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def create_session(self, mode: ChatMode) -> ChatSession:
        async with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"INSERT INTO chat_sessions (mode) VALUES (%s::chat_mode)"  # noqa: S608
                f" RETURNING {SESSION_COLUMNS}",
                (mode.value,),
            )
            row = await cur.fetchone()
        if row is None:
            raise RuntimeError("INSERT ... RETURNING returned no row")
        return _session(row)

    async def list_sessions(self) -> list[ChatSession]:
        async with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"SELECT {SESSION_COLUMNS} FROM chat_sessions"  # noqa: S608
                " ORDER BY updated_at DESC, created_at DESC, id"
            )
            rows = await cur.fetchall()
        return [_session(row) for row in rows]

    async def get_session(self, session_id: UUID) -> ChatSession | None:
        async with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"SELECT {SESSION_COLUMNS} FROM chat_sessions WHERE id = %s",  # noqa: S608
                (session_id,),
            )
            row = await cur.fetchone()
        return _session(row) if row else None

    async def delete_session(self, session_id: UUID) -> bool:
        async with self._pool.connection() as conn:
            cursor = await conn.execute("DELETE FROM chat_sessions WHERE id = %s", (session_id,))
            return cursor.rowcount > 0

    async def list_turns(self, session_id: UUID) -> list[Turn]:
        async with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"SELECT {TURN_COLUMNS} FROM chat_turns"  # noqa: S608
                " WHERE session_id = %s ORDER BY seq",
                (session_id,),
            )
            rows = await cur.fetchall()
        return [_turn(row) for row in rows]

    async def recent_turns(self, session_id: UUID, limit: int) -> list[Turn]:
        async with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"SELECT {TURN_COLUMNS} FROM chat_turns"  # noqa: S608
                " WHERE session_id = %s ORDER BY seq DESC LIMIT %s",
                (session_id, limit),
            )
            rows = await cur.fetchall()
        return [_turn(row) for row in reversed(rows)]

    async def save_turn(self, session_id: UUID, draft: TurnDraft) -> Turn:
        sources = Jsonb([source.model_dump() for source in draft.sources])
        async with self._pool.connection() as conn:
            async with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "SELECT id FROM chat_sessions WHERE id = %s FOR UPDATE", (session_id,)
                )
                if await cur.fetchone() is None:
                    raise SessionNotFoundError
                await cur.execute(
                    "INSERT INTO chat_turns (session_id, seq, question, answer, sources,"  # noqa: S608
                    " endpoint, model, degraded, started_at, finished_at)"
                    " SELECT %s, coalesce(max(seq), 0) + 1, %s, %s, %s, %s, %s, %s, %s, %s"
                    f" FROM chat_turns WHERE session_id = %s RETURNING {TURN_COLUMNS}",
                    (
                        session_id,
                        draft.question,
                        draft.answer,
                        sources,
                        draft.endpoint,
                        draft.model,
                        draft.degraded,
                        draft.started_at,
                        draft.finished_at,
                        session_id,
                    ),
                )
                row = await cur.fetchone()
                await cur.execute(
                    "UPDATE chat_sessions SET title = coalesce(title, %s), updated_at = %s"
                    " WHERE id = %s",
                    (draft.question[:TITLE_LENGTH], draft.finished_at, session_id),
                )
        if row is None:
            raise RuntimeError("INSERT ... RETURNING returned no row")
        return _turn(row)

import inspect
from collections.abc import AsyncGenerator
from dataclasses import asdict
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from ai_second_brain.chat.events import TurnEvent, TurnEventStream
from ai_second_brain.chat.models import ChatMode, ChatSession
from ai_second_brain.chat.repository import ChatRepository
from ai_second_brain.chat.service import ChatService
from ai_second_brain.interfaces.api.deps import get_settings, require_same_origin, require_session
from ai_second_brain.interfaces.api.schemas import (
    AskRequest,
    ChatStatusResponse,
    CloudTierStatus,
    CreateSessionRequest,
    EndpointStatusOut,
    ErrorResponse,
    PrivateTierStatus,
    SessionDetail,
)
from ai_second_brain.interfaces.api.sse import sse_stream

router = APIRouter(tags=["chat"], dependencies=[Depends(require_session)])

ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}
NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"model": ErrorResponse}}
CONFLICT: dict[int | str, dict[str, Any]] = {409: {"model": ErrorResponse}}


class TurnResponse(StreamingResponse):
    """Streaming response that owns a session reservation.

    Starlette can drop a response before it iterates the body (client gone before
    the start message is sent); the turn generator's own `finally` never runs then,
    so the reservation is released here if the turn never started."""

    def __init__(
        self,
        turn: AsyncGenerator[TurnEvent, None],
        content: AsyncGenerator[str, None],
        chat: ChatService,
        session_id: UUID,
    ) -> None:
        super().__init__(
            content,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )
        self._turn = turn
        self._chat = chat
        self._session_id = session_id

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            if inspect.getasyncgenstate(self._turn) == inspect.AGEN_CREATED:
                self._chat.release(self._session_id)
                await self._turn.aclose()


def get_chat(request: Request) -> ChatService:
    return request.app.state.chat


def get_repo(request: Request) -> ChatRepository:
    return request.app.state.chat_repo


@router.get(
    "/chat/status", operation_id="chatStatus", response_model=ChatStatusResponse, responses=ERRORS
)
async def chat_status(request: Request) -> ChatStatusResponse:
    statuses = await request.app.state.ollama.status()
    settings = get_settings(request)
    return ChatStatusResponse(
        private=PrivateTierStatus(
            available=any(s.reachable for s in statuses),
            endpoints=[EndpointStatusOut(**asdict(s)) for s in statuses],
        ),
        cloud=CloudTierStatus(
            available=settings.cloud_available,
            model=settings.anthropic_model if settings.cloud_available else None,
        ),
    )


@router.post(
    "/sessions",
    operation_id="createSession",
    status_code=status.HTTP_201_CREATED,
    response_model=ChatSession,
    dependencies=[Depends(require_same_origin)],
    responses={**ERRORS, **CONFLICT},
)
async def create_session(body: CreateSessionRequest, request: Request) -> ChatSession:
    if body.mode is ChatMode.CLOUD and not get_chat(request).cloud_available:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="cloud_unavailable")
    return await get_repo(request).create_session(body.mode)


@router.get(
    "/sessions", operation_id="listSessions", response_model=list[ChatSession], responses=ERRORS
)
async def list_sessions(request: Request) -> list[ChatSession]:
    return await get_repo(request).list_sessions()


@router.get(
    "/sessions/{session_id}",
    operation_id="getSession",
    response_model=SessionDetail,
    responses={**ERRORS, **NOT_FOUND},
)
async def get_session(session_id: UUID, request: Request) -> SessionDetail:
    repo = get_repo(request)
    session = await repo.get_session(session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not_found")
    turns = await repo.list_turns(session_id)
    return SessionDetail(**session.model_dump(), turns=turns)


@router.delete(
    "/sessions/{session_id}",
    operation_id="deleteSession",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    dependencies=[Depends(require_same_origin)],
    responses={**ERRORS, **NOT_FOUND},
)
async def delete_session(session_id: UUID, request: Request) -> None:
    if not await get_repo(request).delete_session(session_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not_found")


@router.post(
    "/sessions/{session_id}/turns",
    operation_id="askTurn",
    response_class=StreamingResponse,
    dependencies=[Depends(require_same_origin)],
    responses={
        200: {
            "model": TurnEventStream,
            "description": "text/event-stream; each `data:` line is one TurnEvent",
            "content": {"text/event-stream": {}},
        },
        **ERRORS,
        **NOT_FOUND,
        **CONFLICT,
    },
)
async def ask_turn(session_id: UUID, body: AskRequest, request: Request) -> StreamingResponse:
    session = await get_repo(request).get_session(session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not_found")
    chat = get_chat(request)
    if not chat.reserve(session_id):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="turn_in_progress")
    turn = chat.run_turn(session, body.question, reserved=True)
    return TurnResponse(
        turn, sse_stream(turn, request.app.state.sse_ping_interval), chat, session_id
    )

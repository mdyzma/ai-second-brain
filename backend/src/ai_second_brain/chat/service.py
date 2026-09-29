"""One chat turn: route → retrieve → generate → save. Yields events; logs no content."""

import logging
import time
from collections.abc import AsyncGenerator, Callable, Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from ai_second_brain.chat.errors import ChatError, error_message
from ai_second_brain.chat.events import (
    DoneEvent,
    ErrorEvent,
    ReceiptEvent,
    SourcesEvent,
    StatusEvent,
    TokenEvent,
    TurnEvent,
)
from ai_second_brain.chat.models import ChatSession, Source, Tier, Turn, TurnDraft, utc_now
from ai_second_brain.chat.policy import route
from ai_second_brain.chat.prompts import build_messages, system_prompt
from ai_second_brain.chat.providers.base import ChatProvider
from ai_second_brain.chat.repository import STORAGE_ERRORS, ChatRepository
from ai_second_brain.chat.retrieval import Retriever

logger = logging.getLogger("ai_second_brain.chat")

HISTORY_PAIRS = 10
SOURCE_LIMIT = 8


class ProviderPool(Protocol):
    async def select(self) -> ChatProvider: ...


class ChatService:
    def __init__(
        self,
        repository: ChatRepository,
        retriever: Retriever,
        local: ProviderPool,
        cloud: Callable[[], ChatProvider] | None,
        *,
        clock: Callable[[], datetime] = utc_now,
        timer: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._repository = repository
        self._retriever = retriever
        self._local = local
        self._cloud = cloud
        self._clock = clock
        self._timer = timer
        self._active: set[UUID] = set()

    @property
    def cloud_available(self) -> bool:
        return self._cloud is not None

    def is_busy(self, session_id: UUID) -> bool:
        return session_id in self._active

    async def run_turn(
        self, session: ChatSession, question: str
    ) -> AsyncGenerator[TurnEvent, None]:
        if session.id in self._active:
            yield _error(ChatError("turn_in_progress", "chat"), session)
            return
        self._active.add(session.id)
        started_at, started = self._clock(), self._timer()
        outcome, endpoint, model = "interrupted", "-", "-"
        try:
            yield StatusEvent(phase="retrieving")
            tier = route(session.mode)
            sources = await self._retrieve(question) if tier is Tier.LOCAL else []
            yield SourcesEvent(items=sources, disabled=tier is Tier.CLOUD)
            yield StatusEvent(phase="connecting")
            provider = await self._provider(tier)
            endpoint, model = provider.label, provider.model
            history = await self._history(session.id)
            messages = build_messages(session.mode, history, question, sources)
            yield StatusEvent(
                phase="generating", endpoint=endpoint, model=model, degraded=provider.degraded
            )
            parts: list[str] = []
            async for text in provider.stream(system_prompt(session.mode), messages):
                parts.append(text)
                yield TokenEvent(text=text)
            answer = "".join(parts)
            if not answer.strip():
                raise ChatError("provider_error", provider.component)
            turn = await self._save(
                session.id,
                TurnDraft(
                    question=question,
                    answer=answer,
                    sources=sources,
                    endpoint=endpoint,
                    model=model,
                    degraded=provider.degraded,
                    started_at=started_at,
                    finished_at=self._clock(),
                ),
            )
            outcome = "ok"
            yield ReceiptEvent(
                turn_id=turn.id,
                seq=turn.seq,
                endpoint=endpoint,
                model=model,
                degraded=provider.degraded,
                duration_ms=self._elapsed_ms(started),
            )
            yield DoneEvent()
        except ChatError as error:
            outcome = f"error:{error.code}"
            yield _error(error, session)
        finally:
            self._active.discard(session.id)
            logger.info(
                "chat turn mode=%s endpoint=%s model=%s outcome=%s duration_ms=%d",
                session.mode.value,
                endpoint,
                model,
                outcome,
                self._elapsed_ms(started),
            )

    def _elapsed_ms(self, started: float) -> int:
        return round((self._timer() - started) * 1000)

    async def _retrieve(self, question: str) -> list[Source]:
        try:
            found: Sequence[Source] = await self._retriever.retrieve(question, SOURCE_LIMIT)
        except Exception:  # any retriever failure is reported, never its details
            raise ChatError("retrieval_error", "retrieval") from None
        return [
            source.model_copy(update={"n": index})
            for index, source in enumerate(found[:SOURCE_LIMIT], start=1)
        ]

    async def _provider(self, tier: Tier) -> ChatProvider:
        if tier is Tier.LOCAL:
            return await self._local.select()
        if self._cloud is None:
            raise ChatError("cloud_unavailable", "anthropic")
        return self._cloud()

    async def _history(self, session_id: UUID) -> list[Turn]:
        try:
            return await self._repository.recent_turns(session_id, HISTORY_PAIRS)
        except STORAGE_ERRORS:
            raise ChatError("storage_error", "db") from None

    async def _save(self, session_id: UUID, draft: TurnDraft) -> Turn:
        try:
            return await self._repository.save_turn(session_id, draft)
        except STORAGE_ERRORS:
            raise ChatError("storage_error", "db") from None


def _error(error: ChatError, session: ChatSession) -> ErrorEvent:
    return ErrorEvent(
        code=error.code,
        component=error.component,
        message=error_message(error.code, session.mode),
    )

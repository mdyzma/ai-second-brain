"""Behaviour every ChatRepository must have. Subclasses implement `run`."""

from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from ai_second_brain.chat.models import ChatMode, Source, TurnDraft
from ai_second_brain.chat.repository import ChatRepository, SessionNotFoundError

Scenario = Callable[[ChatRepository], Coroutine[Any, Any, None]]
BASE = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


def draft(question: str = "What is Proxmox?", *, minutes: int = 0) -> TurnDraft:
    return TurnDraft(
        question=question,
        answer="A hypervisor.",
        sources=[Source(n=1, source_id="s1", path="notes/proxmox.md", score=0.8, snippet="x")],
        endpoint="workstation",
        model="qwen3:32b",
        degraded=False,
        started_at=BASE + timedelta(minutes=minutes),
        finished_at=BASE + timedelta(minutes=minutes, seconds=5),
    )


class RepositoryContract:
    def run(self, scenario: Scenario) -> None:
        raise NotImplementedError

    def test_create_and_get(self) -> None:
        async def scenario(repo: ChatRepository) -> None:
            created = await repo.create_session(ChatMode.CLOUD)
            assert created.mode is ChatMode.CLOUD
            assert created.title is None
            assert await repo.get_session(created.id) == created
            assert await repo.get_session(uuid4()) is None

        self.run(scenario)

    def test_save_turn_numbers_sequentially_and_sets_title(self) -> None:
        async def scenario(repo: ChatRepository) -> None:
            session = await repo.create_session(ChatMode.PRIVATE)
            long_question = "Q" * 200
            first = await repo.save_turn(session.id, draft(long_question))
            second = await repo.save_turn(session.id, draft("Second?", minutes=1))
            assert (first.seq, second.seq) == (1, 2)
            assert first.sources[0].path == "notes/proxmox.md"
            reloaded = await repo.get_session(session.id)
            assert reloaded is not None
            assert reloaded.title == "Q" * 80
            assert reloaded.updated_at == second.finished_at
            turns = await repo.list_turns(session.id)
            assert [t.question for t in turns] == [long_question, "Second?"]

        self.run(scenario)

    def test_recent_turns_are_the_latest_oldest_first(self) -> None:
        async def scenario(repo: ChatRepository) -> None:
            session = await repo.create_session(ChatMode.PRIVATE)
            for index in range(12):
                await repo.save_turn(session.id, draft(f"q{index}", minutes=index))
            recent = await repo.recent_turns(session.id, 10)
            assert [t.question for t in recent] == [f"q{i}" for i in range(2, 12)]

        self.run(scenario)

    def test_list_sessions_most_recently_updated_first(self) -> None:
        async def scenario(repo: ChatRepository) -> None:
            older = await repo.create_session(ChatMode.PRIVATE)
            newer = await repo.create_session(ChatMode.PRIVATE)
            later = draft(minutes=24 * 60 * 365 * 5)  # finished far in the future
            await repo.save_turn(older.id, later)
            ids = [s.id for s in await repo.list_sessions()]
            assert ids.index(older.id) < ids.index(newer.id)

        self.run(scenario)

    def test_delete_cascades_and_reports(self) -> None:
        async def scenario(repo: ChatRepository) -> None:
            session = await repo.create_session(ChatMode.PRIVATE)
            await repo.save_turn(session.id, draft())
            assert await repo.delete_session(session.id) is True
            assert await repo.get_session(session.id) is None
            assert await repo.list_turns(session.id) == []
            assert await repo.delete_session(session.id) is False

        self.run(scenario)

    def test_save_turn_to_missing_session_raises(self) -> None:
        async def scenario(repo: ChatRepository) -> None:
            with pytest.raises(SessionNotFoundError):
                await repo.save_turn(uuid4(), draft())

        self.run(scenario)

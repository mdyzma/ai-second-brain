from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from procrastinate.jobs import Job

from ai_second_brain.knowledge.embedder import EMBED_RETRY_SECONDS, EmbedRetryable
from ai_second_brain.knowledge.jobs import embed_revision_task


def strategy() -> Any:
    return embed_revision_task.retry_strategy


def job(attempts: int) -> Job:
    return cast(Job, SimpleNamespace(attempts=attempts))


@pytest.mark.parametrize(("attempts", "seconds"), list(enumerate(EMBED_RETRY_SECONDS)))
def test_retryable_follows_schedule(attempts: int, seconds: int) -> None:
    decision = strategy().get_retry_decision(exception=EmbedRetryable(), job=job(attempts))
    assert decision is not None
    delay = (decision.retry_at - datetime.now(UTC)).total_seconds()
    assert seconds - 5 < delay <= seconds


def test_schedule_values() -> None:
    assert EMBED_RETRY_SECONDS == (30, 60, 120, 300, 600, 1200, 2400, 3600)


def test_gives_up_after_schedule() -> None:
    result = strategy().get_retry_decision(
        exception=EmbedRetryable(), job=job(len(EMBED_RETRY_SECONDS))
    )
    assert result is None


def test_other_exceptions_not_retried() -> None:
    assert strategy().get_retry_decision(exception=RuntimeError("x"), job=job(0)) is None

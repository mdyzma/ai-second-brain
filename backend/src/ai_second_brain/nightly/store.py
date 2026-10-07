"""SQL on nightly_runs (spec §4). Callers own commits; each function is one statement."""

from datetime import date
from typing import Any, Literal
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row

Trigger = Literal["schedule", "manual"]


async def insert_run(conn: AsyncConnection, *, run_date: date, trigger: Trigger) -> UUID | None:
    """A new running run, or None when a scheduled run exists for the day or one is open."""
    try:
        async with conn.transaction():
            cur = await conn.execute(
                "INSERT INTO nightly_runs (run_date, trigger, window_start)"
                " VALUES (%s, %s, coalesce((SELECT max(started_at) FROM nightly_runs"
                "  WHERE status <> 'failed'), '-infinity'))"
                " RETURNING id",
                (run_date, trigger),
            )
            row = await cur.fetchone()
    except UniqueViolation:
        return None
    return row[0] if row else None


async def open_run(conn: AsyncConnection) -> dict[str, Any] | None:
    """The open run, or None. `window_start` is None for the first run (no earlier window),
    because the driver cannot load -infinity."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT id, run_date, trigger, status,"
            " CASE WHEN window_start = '-infinity' THEN NULL ELSE window_start END AS window_start,"
            " started_at, finished_at, queued_new, queued_failed, timed_out, unavailable, error"
            " FROM nightly_runs WHERE status = 'running'"
        )
        return await cur.fetchone()


async def has_scheduled_run(conn: AsyncConnection, run_date: date) -> bool:
    cur = await conn.execute(
        "SELECT EXISTS (SELECT 1 FROM nightly_runs WHERE run_date = %s"
        " AND trigger = 'schedule' AND status <> 'failed')",
        (run_date,),
    )
    row = await cur.fetchone()
    return bool(row and row[0])


async def set_counts(
    conn: AsyncConnection, run_id: UUID, queued_new: int, queued_failed: int
) -> None:
    """Counts land only on a run that is still open, never on one already closed."""
    await conn.execute(
        "UPDATE nightly_runs SET queued_new = %s, queued_failed = %s"
        " WHERE id = %s AND status = 'running'",
        (queued_new, queued_failed, run_id),
    )


async def finish(
    conn: AsyncConnection, run_id: UUID, *, timed_out: bool = False, unavailable: bool = False
) -> None:
    await conn.execute(
        "UPDATE nightly_runs SET status = 'complete', finished_at = now(),"
        " timed_out = %s, unavailable = %s WHERE id = %s AND status = 'running'",
        (timed_out, unavailable, run_id),
    )


async def fail(conn: AsyncConnection, run_id: UUID, code: str) -> None:
    await conn.execute(
        "UPDATE nightly_runs SET status = 'failed', finished_at = now(), error = %s"
        " WHERE id = %s AND status = 'running'",
        (code, run_id),
    )

"""Read-side graph queries: status counts and the revisions still to extract."""

import logging
from typing import Any, Literal
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.pq import TransactionStatus

from ai_second_brain.graph.schema import ENTITY_TYPES
from ai_second_brain.knowledge.queue import JobQueue

logger = logging.getLogger("ai_second_brain.graph")
STATUSES = ("proposed", "accepted", "rejected")

# Current revisions of live sources, each with its extraction row (if any) for one version.
_LIVE = (
    "FROM sources s LEFT JOIN extractions e"
    " ON e.revision_id = s.current_revision_id AND e.extractor_version = %s"
    " WHERE s.deleted_at IS NULL AND s.current_revision_id IS NOT NULL"
)


async def graph_status(conn: AsyncConnection, version: str) -> dict[str, Any]:
    """Spec section 8 `graphStatus`, minus the model, availability and queue depth."""
    cur = await conn.execute(
        "SELECT count(*), count(*) FILTER (WHERE e.status = 'ok'),"
        " count(*) FILTER (WHERE e.status = 'failed') " + _LIVE,
        (version,),
    )
    row = await cur.fetchone()
    total, extracted, failed = (int(v) for v in row) if row else (0, 0, 0)
    entities: dict[str, dict[str, int]] = {t: dict.fromkeys(STATUSES, 0) for t in ENTITY_TYPES}
    cur = await conn.execute(
        "SELECT type::text, status::text, count(*) FROM entities GROUP BY 1, 2"
    )
    for etype, status, count in await cur.fetchall():
        entities.setdefault(etype, dict.fromkeys(STATUSES, 0))[status] = int(count)
    return {
        "extractor_version": version,
        "revisions": {
            "total": total,
            "extracted": extracted,
            "failed": failed,
            "pending": total - extracted - failed,
        },
        "entities": entities,
    }


async def pending_revisions(conn: AsyncConnection, version: str) -> list[UUID]:
    """Current revisions of live sources with no extraction row (ok or failed) at `version`."""
    cur = await conn.execute(
        "SELECT s.current_revision_id " + _LIVE + " AND e.revision_id IS NULL ORDER BY s.id",
        (version,),
    )
    return [r[0] for r in await cur.fetchall()]


async def failed_revisions(conn: AsyncConnection, version: str) -> list[UUID]:
    cur = await conn.execute(
        "SELECT s.current_revision_id " + _LIVE + " AND e.status = 'failed' ORDER BY s.id",
        (version,),
    )
    return [r[0] for r in await cur.fetchall()]


async def queue_extraction(
    conn: AsyncConnection, queue: JobQueue, version: str, scope: Literal["new", "failed"]
) -> int:
    """Defer one job per revision; returns how many were newly queued (a lock hit is not one)."""
    ids = await (failed_revisions if scope == "failed" else pending_revisions)(conn, version)
    if conn.info.transaction_status != TransactionStatus.IDLE:
        await conn.commit()  # never hold a transaction open while deferring thousands of jobs
    queued = 0
    for revision_id in ids:
        if await queue.extract_revision(revision_id):
            queued += 1
    logger.info("graph_extract_queued scope=%s candidates=%d queued=%d", scope, len(ids), queued)
    return queued

"""Observe one vault file: record a revision, then queue indexing after commit."""

import asyncio
import logging

from ai_second_brain.knowledge import store
from ai_second_brain.knowledge.context import IngestContext
from ai_second_brain.knowledge.store import ObserveOutcome
from ai_second_brain.vault.read import read_note

logger = logging.getLogger("ai_second_brain.ingest")


async def observe(ctx: IngestContext, rel: str) -> ObserveOutcome | None:
    """Returns None when the file couldn't be read (io_error)."""
    if ctx.vault is None:
        raise RuntimeError("vault is not configured")
    try:
        note = await asyncio.to_thread(read_note, ctx.vault.abs(rel), ctx.settings.max_note_bytes)
    except OSError:
        logger.info("observe outcome=io_error")
        return None
    async with ctx.pool.connection() as conn, conn.transaction():
        outcome = await store.record_observation(conn, rel, note)
    if outcome.queue_index:
        await ctx.queue.index_source(outcome.source_id)
    logger.info("observe source=%s action=%s", outcome.source_id, outcome.action)
    return outcome

"""Extraction job body: windows -> local model -> validated JSON -> an `extractions` row."""

import json
import logging
import time
from pathlib import PurePosixPath
from typing import Any, Literal
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.errors import DeadlockDetected, SerializationFailure

from ai_second_brain.graph import store
from ai_second_brain.graph.context import GraphContext
from ai_second_brain.graph.names import norm
from ai_second_brain.graph.prompt import EXTRACTOR_VERSION, SYSTEM_PROMPT, build_user_message
from ai_second_brain.graph.resolve import NameVectors, ResolveCounts, embed_names, resolve
from ai_second_brain.graph.schema import (
    ExtractionOutput,
    InvalidOutput,
    filter_output,
    output_json_schema,
)
from ai_second_brain.graph.windows import Window, merge_outputs, split_windows

logger = logging.getLogger("ai_second_brain.graph")
Outcome = Literal["ok", "skipped", "failed"]


async def _call(
    ctx: GraphContext, messages: list[dict[str, str]], stem: str
) -> ExtractionOutput | None:
    """One window; one retry carrying only the short reason (never note content)."""
    assert ctx.client is not None  # noqa: S101 - checked by the caller
    schema = output_json_schema()
    for attempt in range(2):
        reply = await ctx.client.chat_json(messages, schema)
        try:
            return filter_output(json.loads(reply), filename_stem=stem)
        except (ValueError, InvalidOutput) as error:  # JSONDecodeError is a ValueError
            if attempt == 1:
                return None
            reason = str(error) if isinstance(error, InvalidOutput) else "not JSON"
            messages = [
                *messages,
                {"role": "assistant", "content": reply},
                {
                    "role": "user",
                    "content": f"Your reply was invalid ({reason}). "
                    "Reply again with JSON matching the schema.",
                },
            ]
    return None


def _evidence(window: Window, out: ExtractionOutput, evidence: dict[str, str]) -> None:
    """Window-local chunk labels -> chunk ids; first valid relation wins per key."""
    types = {norm(e.name): e.type for e in out.entities}
    for rel in out.relations:
        chunk_id = window.labels.get(rel.chunk) if rel.chunk else None
        if chunk_id is None:
            continue
        subject, obj = norm(rel.subject), norm(rel.object)
        evidence.setdefault(json.dumps([subject, rel.relation, obj]), str(chunk_id))
        for name in (subject, obj):
            if name in types:
                evidence.setdefault(json.dumps(["entity", types[name], name]), str(chunk_id))


async def _still_current(conn: AsyncConnection, revision_id: UUID) -> bool:
    """Lock the source row and re-check, so a stale result is never written."""
    cur = await conn.execute(
        "SELECT s.current_revision_id = r.id AS current, s.deleted_at IS NULL AS live"
        " FROM source_revisions r JOIN sources s ON s.id = r.source_id"
        " WHERE r.id = %s FOR UPDATE OF s",
        (revision_id,),
    )
    row = await cur.fetchone()
    return row is not None and bool(row[0]) and bool(row[1])


async def _finish(
    conn: AsyncConnection,
    ctx: GraphContext,
    *,
    source_id: UUID,
    revision_id: UUID,
    output: dict[str, Any],
    vectors: NameVectors,
) -> ResolveCounts:
    """Resolution runs here, inside the transaction recording the extraction."""
    return await resolve(
        conn, ctx, source_id=source_id, revision_id=revision_id, output=output, vectors=vectors
    )


async def extract_revision(ctx: GraphContext, revision_id: UUID) -> Outcome:
    started = time.monotonic()
    model = ctx.client.model if ctx.client else ""

    async def fail(code: str) -> Outcome:
        async with ctx.pool.connection() as conn:
            if not await _still_current(conn, revision_id):
                logger.info("extract revision=%s outcome=skipped code=stale", revision_id)
                return "skipped"
            await store.record_extraction(
                conn, revision_id, EXTRACTOR_VERSION, status="failed", model=model, error=code
            )
        logger.info("extract revision=%s outcome=failed code=%s", revision_id, code)
        return "failed"

    async with ctx.pool.connection() as conn:
        info = await store.revision_info(conn, revision_id)
        if (
            info is None
            or not info.is_current
            or not info.live
            or await store.has_ok_extraction(conn, revision_id, EXTRACTOR_VERSION)
        ):
            logger.info("extract revision=%s outcome=skipped", revision_id)
            return "skipped"
        chunks = await store.revision_chunks(conn, revision_id)
    if ctx.client is None:
        return await fail("extraction_unavailable")
    windows = split_windows(chunks, max_chars=ctx.settings.extract_window_chars)
    stem = PurePosixPath(info.path).stem
    outputs: list[ExtractionOutput] = []
    evidence: dict[str, str] = {}
    for index, window in enumerate(windows, 1):
        user = build_user_message(
            title=info.title, path=info.path, window=window, index=index, total=len(windows)
        )
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]
        out = await _call(ctx, messages, stem)
        if out is None:
            return await fail("invalid_output")
        _evidence(window, out, evidence)  # before the merge makes chunk labels stale
        outputs.append(out)
    merged = merge_outputs(outputs)
    output: dict[str, Any] = merged.model_dump() | {"evidence": evidence}
    vectors = await embed_names(ctx, merged)  # network first: never under the source lock
    source_id = info.source_id

    async def write() -> ResolveCounts | None:
        """One write transaction; None when the revision went stale."""
        async with ctx.pool.connection() as conn:
            if not await _still_current(conn, revision_id):
                return None
            await store.record_extraction(
                conn,
                revision_id,
                EXTRACTOR_VERSION,
                status="ok",
                model=model,
                summary=merged.summary,
                output=output,
            )
            return await _finish(
                conn,
                ctx,
                source_id=source_id,
                revision_id=revision_id,
                output=output,
                vectors=vectors,
            )

    try:
        counts = await write()
    except (DeadlockDetected, SerializationFailure) as error:
        # Rolled back; re-run only the DB part with the same model output (never the model).
        logger.warning(
            "extract revision=%s code=write_retry error=%s", revision_id, type(error).__name__
        )
        counts = await write()  # a second failure raises, for the job's retry
    if counts is None:
        logger.info("extract revision=%s outcome=skipped code=stale", revision_id)
        return "skipped"
    for entity_id in counts.created_ids:  # after the commit (the 2a defer-after-commit rule)
        await ctx.queue.embed_entity(entity_id)
    logger.info(
        "extract revision=%s windows=%d entities=%d relations=%d created=%d linked=%d"
        " accepted=%d proposed=%d dropped=%d outcome=ok ms=%d",
        revision_id,
        len(windows),
        len(merged.entities),
        len(merged.relations),
        counts.created,
        counts.linked,
        counts.accepted,
        counts.proposed,
        counts.dropped,
        int((time.monotonic() - started) * 1000),
    )
    return "ok"

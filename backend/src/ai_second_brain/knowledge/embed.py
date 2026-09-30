"""embed_revision: batch chunks to Ollama /api/embed; each batch commits on its own."""

import logging
from uuid import UUID

from psycopg.errors import ForeignKeyViolation

from ai_second_brain.knowledge import store
from ai_second_brain.knowledge.context import IngestContext
from ai_second_brain.knowledge.embed_text import embed_input
from ai_second_brain.knowledge.embedder import EMBED_RETRY_SECONDS, EmbedError, EmbedRetryable

__all__ = ["EMBED_RETRY_SECONDS", "EmbedRetryable", "embed_revision"]

logger = logging.getLogger("ai_second_brain.ingest")


async def embed_revision(ctx: IngestContext, revision_id: UUID, space_id: int) -> None:
    async with ctx.pool.connection() as conn:
        target = await store.revision_for_embedding(conn, revision_id)
        if target is None or not target.is_current:
            return
        pending = await store.chunks_to_embed(conn, revision_id, space_id)
    if not pending:
        async with ctx.pool.connection() as conn:
            await store.clear_embed_error(conn, revision_id)
        return
    if ctx.embedder is None:
        async with ctx.pool.connection() as conn:
            await store.set_embed_error(conn, revision_id, "embed_unreachable")
        raise EmbedRetryable
    batch = ctx.settings.embed_batch
    for start in range(0, len(pending), batch):
        part = pending[start : start + batch]
        texts = [embed_input(target.title, path, content) for _, path, content in part]
        try:
            vectors = await ctx.embedder.embed(texts)
        except EmbedError as error:
            async with ctx.pool.connection() as conn:
                await store.set_embed_error(conn, revision_id, error.code)
            logger.info("embed revision=%s outcome=error:%s", revision_id, error.code)
            if error.code == "embed_unreachable":
                raise EmbedRetryable from None
            return
        rows = [(cid, v) for (cid, _, _), v in zip(part, vectors, strict=True)]
        try:
            async with ctx.pool.connection() as conn, conn.transaction():
                await store.write_embeddings(conn, space_id, rows)
        except ForeignKeyViolation:
            # The revision was superseded or deleted mid-run; its chunks are gone.
            logger.info("embed revision=%s outcome=stale", revision_id)
            return
    async with ctx.pool.connection() as conn:
        await store.clear_embed_error(conn, revision_id)
    logger.info("embed revision=%s chunks=%d outcome=ok", revision_id, len(pending))

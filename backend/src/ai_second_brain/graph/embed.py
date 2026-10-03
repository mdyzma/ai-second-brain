"""graph_embed_entity: embed an entity's name into the default space; idempotent."""

import logging
from uuid import UUID

from psycopg.errors import ForeignKeyViolation

from ai_second_brain.graph import store
from ai_second_brain.knowledge.context import IngestContext
from ai_second_brain.knowledge.embedder import EmbedError, EmbedRetryable

logger = logging.getLogger("ai_second_brain.graph")


async def embed_entity(ctx: IngestContext, entity_id: UUID) -> None:
    async with ctx.pool.connection() as conn:
        cur = await conn.execute("SELECT name FROM entities WHERE id = %s", (entity_id,))
        row = await cur.fetchone()
        if row is None or not await store.missing_embedding(conn, entity_id, ctx.space_id):
            return  # gone, or already embedded
    if ctx.embedder is None:
        raise EmbedRetryable
    try:
        [vector] = await ctx.embedder.embed([row[0]])
    except EmbedError as error:
        logger.info("embed_entity entity=%s outcome=error:%s", entity_id, error.code)
        if error.code == "embed_unreachable":
            raise EmbedRetryable from None
        return
    try:
        async with ctx.pool.connection() as conn:
            await store.upsert_entity_embedding(conn, entity_id, ctx.space_id, vector)
    except ForeignKeyViolation:  # deleted or merged meanwhile
        return
    logger.info("embed_entity entity=%s outcome=ok", entity_id)

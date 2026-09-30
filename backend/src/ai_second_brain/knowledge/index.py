"""index_source: newest pending revision → chunks → swap, in one transaction."""

import logging
from pathlib import PurePosixPath
from uuid import UUID

from ai_second_brain.knowledge import store
from ai_second_brain.knowledge.context import IngestContext
from ai_second_brain.vault.chunk import chunk_note
from ai_second_brain.vault.parse import parse_note

logger = logging.getLogger("ai_second_brain.ingest")


async def index_source(ctx: IngestContext, source_id: UUID) -> None:
    async with ctx.pool.connection() as conn, conn.transaction():
        claimed = await store.claim_pending(conn, source_id)
        if claimed is None:
            return
        parsed = parse_note(claimed.raw_text, PurePosixPath(claimed.external_ref).stem)
        chunks = chunk_note(parsed.body)
        await store.insert_chunks(conn, claimed.revision_id, chunks)
        if claimed.previous_revision_id is not None:
            await store.supersede_revision(conn, claimed.previous_revision_id)
        metadata = {
            "frontmatter": parsed.frontmatter,
            "frontmatter_error": parsed.frontmatter_error,
            "links": parsed.links,
        }
        await store.finish_index(conn, source_id, claimed.revision_id, parsed.title, metadata)
    await ctx.queue.embed_revision(claimed.revision_id, ctx.space_id)
    logger.info(
        "index source=%s revision=%s chunks=%d", source_id, claimed.revision_id, len(chunks)
    )

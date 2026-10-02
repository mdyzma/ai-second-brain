"""Copy live, current notes from the dev DB (read-only) into the scratch DB.

Safety: the dev connection is only ever used inside `read_only_transaction`, whose first
statement is `SET TRANSACTION READ ONLY`, so PostgreSQL itself refuses any write to dev.
The scratch side is truncated only after it is shown to be a different, prepared database.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, LiteralString

from psycopg import AsyncConnection
from psycopg.pq import TransactionStatus

from ai_second_brain.eval.database import check_ready
from ai_second_brain.eval.queries import EvalConfigError

# (table, target columns, dev SELECT). Live = not deleted and with a current revision.
# Never the generated `chunks.tsv`: the scratch DB regenerates it.
# `sources.current_revision_id` is set after the revisions exist (circular FK).
_COPIES: list[tuple[LiteralString, LiteralString, LiteralString]] = [
    (
        "sources",
        "id, kind, external_ref, title, sensitivity, salience, created_at",
        "SELECT s.id, s.kind, s.external_ref, s.title, s.sensitivity, s.salience, s.created_at"
        " FROM sources s"
        " WHERE s.deleted_at IS NULL AND s.current_revision_id IS NOT NULL",
    ),
    (
        "source_revisions",
        "id, source_id, content_hash, raw_text, metadata, state, error, observed_at,"
        " indexed_at, tags",
        "SELECT r.id, r.source_id, r.content_hash, '', r.metadata, r.state, r.error,"
        " r.observed_at, r.indexed_at, r.tags"
        " FROM sources s JOIN source_revisions r ON r.id = s.current_revision_id"
        " WHERE s.deleted_at IS NULL AND s.current_revision_id IS NOT NULL",
    ),
    (
        "chunks",
        "id, revision_id, ordinal, heading_path, heading_text, content",
        "SELECT c.id, c.revision_id, c.ordinal, c.heading_path, c.heading_text, c.content"
        " FROM sources s JOIN chunks c ON c.revision_id = s.current_revision_id"
        " WHERE s.deleted_at IS NULL AND s.current_revision_id IS NOT NULL",
    ),
]


@dataclass(frozen=True)
class SnapshotInfo:
    sources: int
    chunks: int
    taken_at: datetime


@asynccontextmanager
async def read_only_transaction(conn: AsyncConnection[Any]) -> AsyncIterator[None]:
    """A top-level transaction whose very first statement makes it read-only."""
    if conn.info.transaction_status != TransactionStatus.IDLE:
        raise EvalConfigError(["the dev connection must be idle before the snapshot"])
    async with conn.transaction():
        await conn.execute("SET TRANSACTION READ ONLY")
        yield


def _identity(conn: AsyncConnection[Any]) -> tuple[str, int, str]:
    """Where a connection points, from client-side info only (no query is sent)."""
    host = (conn.info.host or "").lower()
    host = "127.0.0.1" if host in ("localhost", "::1") else host
    return host, conn.info.port, conn.info.dbname


async def snapshot(dev: AsyncConnection[Any], ev: AsyncConnection[Any]) -> SnapshotInfo:
    if _identity(dev) == _identity(ev):
        raise EvalConfigError(["the evaluation database is the same database as dev"])
    if ev.info.transaction_status != TransactionStatus.IDLE:
        raise EvalConfigError(["the evaluation connection must be idle before the snapshot"])
    await check_ready(ev)  # the dev DB never has the eval cache: a second guard before TRUNCATE
    async with read_only_transaction(dev), ev.transaction():
        taken_at = datetime.now(UTC)
        await ev.execute("TRUNCATE sources CASCADE")  # revisions, chunks, chunk_embeddings
        await ev.execute("DELETE FROM embedding_spaces WHERE id >= 100")
        for table, columns, select in _COPIES:
            async with (
                dev.cursor() as dev_cur,
                ev.cursor() as ev_cur,
                dev_cur.copy("COPY (" + select + ") TO STDOUT") as source,
                ev_cur.copy("COPY " + table + " (" + columns + ") FROM STDIN") as target,
            ):
                async for block in source:
                    await target.write(block)
        await ev.execute(
            "UPDATE sources s SET current_revision_id = r.id"
            " FROM source_revisions r WHERE r.source_id = s.id"
        )
        sources = (await (await ev.execute("SELECT count(*) FROM sources")).fetchone() or (0,))[0]
        chunks = (await (await ev.execute("SELECT count(*) FROM chunks")).fetchone() or (0,))[0]
    return SnapshotInfo(sources, chunks, taken_at)


async def live_paths(conn: AsyncConnection[Any]) -> set[str]:
    async with conn.transaction():
        cur = await conn.execute(
            "SELECT s.external_ref FROM sources s"
            " WHERE s.deleted_at IS NULL AND s.current_revision_id IS NOT NULL"
        )
        return {row[0] for row in await cur.fetchall()}

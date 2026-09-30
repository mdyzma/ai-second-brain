"""All SQL for sources, revisions, chunks, embeddings and ingest runs. Never logs content."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ai_second_brain.vault.chunk import Chunk
from ai_second_brain.vault.read import ReadNote

ObserveAction = Literal["new", "unchanged", "requeued", "restored", "failed"]


@dataclass(frozen=True)
class ObserveOutcome:
    source_id: UUID
    action: ObserveAction
    queue_index: bool


@dataclass(frozen=True)
class Claimed:
    source_id: UUID
    revision_id: UUID
    raw_text: str
    external_ref: str
    previous_revision_id: UUID | None


async def record_observation(conn: AsyncConnection, rel: str, note: ReadNote) -> ObserveOutcome:
    meta = {"size": note.size, "mtime_ns": note.mtime_ns}
    async with conn.cursor(row_factory=dict_row) as cur:
        # Insert-if-missing first: FOR UPDATE alone locks nothing for a new path, and a unique
        # violation's DETAIL would carry the note path into the logs.
        await cur.execute(
            "INSERT INTO sources (kind, external_ref) VALUES ('obsidian', %s)"
            " ON CONFLICT (kind, external_ref) DO NOTHING",
            (rel,),
        )
        await cur.execute(
            "SELECT id, current_revision_id, deleted_at FROM sources"
            " WHERE kind = 'obsidian' AND external_ref = %s FOR UPDATE",
            (rel,),
        )
        source = await cur.fetchone()
        if source is None:
            raise RuntimeError("source row missing after insert")
        was_deleted = source["deleted_at"] is not None
        if was_deleted:
            await cur.execute("UPDATE sources SET deleted_at = NULL WHERE id = %s", (source["id"],))
        state = "failed" if note.error else "pending"
        await cur.execute(
            "INSERT INTO source_revisions"
            " (source_id, content_hash, raw_text, metadata, state, error)"
            " VALUES (%s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (source_id, content_hash) DO NOTHING RETURNING id",
            (source["id"], note.content_hash, note.text, Jsonb(meta), state, note.error),
        )
        inserted = await cur.fetchone()
        if inserted is not None:
            if note.error:
                return ObserveOutcome(source["id"], "failed", False)
            return ObserveOutcome(source["id"], "new", True)
        await cur.execute(
            "SELECT id, state FROM source_revisions WHERE source_id = %s AND content_hash = %s",
            (source["id"], note.content_hash),
        )
        existing = await cur.fetchone()
        if existing is None:
            raise RuntimeError("revision row vanished under lock")
        is_current = existing["id"] == source["current_revision_id"]
        if existing["state"] == "failed" and note.error:
            return ObserveOutcome(source["id"], "unchanged", False)
        if is_current and existing["state"] == "indexed" and not was_deleted:
            await cur.execute(
                "UPDATE source_revisions SET metadata = metadata || %s WHERE id = %s",
                (Jsonb(meta), existing["id"]),
            )
            # The file equals the indexed revision, so any newer pending edit is stale.
            await cur.execute(
                "UPDATE source_revisions SET state = 'superseded'"
                " WHERE source_id = %s AND state = 'pending' AND id <> %s",
                (source["id"], existing["id"]),
            )
            return ObserveOutcome(source["id"], "unchanged", False)
        if existing["state"] == "pending" and not was_deleted:
            await cur.execute(
                "UPDATE source_revisions SET observed_at = now(), metadata = metadata || %s"
                " WHERE id = %s",
                (Jsonb(meta), existing["id"]),
            )
            return ObserveOutcome(source["id"], "new", True)
        await cur.execute(
            "UPDATE source_revisions SET state = 'pending', error = NULL, observed_at = now(),"
            " metadata = metadata || %s WHERE id = %s",
            (Jsonb(meta), existing["id"]),
        )
        action: ObserveAction = "restored" if was_deleted and is_current else "requeued"
        return ObserveOutcome(source["id"], action, True)


async def claim_pending(conn: AsyncConnection, source_id: UUID) -> Claimed | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT external_ref, current_revision_id FROM sources WHERE id = %s FOR UPDATE",
            (source_id,),
        )
        source = await cur.fetchone()
        if source is None:
            return None
        await cur.execute(
            "SELECT id, raw_text FROM source_revisions WHERE source_id = %s AND state = 'pending'"
            " ORDER BY observed_at DESC, id DESC",
            (source_id,),
        )
        pending = await cur.fetchall()
        if not pending:
            return None
        newest, older = pending[0], pending[1:]
        if older:
            await cur.execute(
                "UPDATE source_revisions SET state = 'superseded' WHERE id = ANY(%s)",
                ([r["id"] for r in older],),
            )
        previous = source["current_revision_id"]
        return Claimed(
            source_id,
            newest["id"],
            newest["raw_text"],
            source["external_ref"],
            previous if previous != newest["id"] else None,
        )


async def insert_chunks(conn: AsyncConnection, revision_id: UUID, chunks: Sequence[Chunk]) -> None:
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM chunks WHERE revision_id = %s", (revision_id,))
        if chunks:
            await cur.executemany(
                "INSERT INTO chunks (revision_id, ordinal, heading_path, content)"
                " VALUES (%s, %s, %s, %s)",
                [(revision_id, c.ordinal, list(c.heading_path), c.content) for c in chunks],
            )


async def delete_revision_chunks(conn: AsyncConnection, revision_id: UUID) -> None:
    await conn.execute("DELETE FROM chunks WHERE revision_id = %s", (revision_id,))


async def supersede_revision(conn: AsyncConnection, revision_id: UUID) -> None:
    await delete_revision_chunks(conn, revision_id)
    await conn.execute(
        "UPDATE source_revisions SET state = 'superseded' WHERE id = %s", (revision_id,)
    )


async def finish_index(
    conn: AsyncConnection, source_id: UUID, revision_id: UUID, title: str, metadata: dict[str, Any]
) -> None:
    await conn.execute(
        "UPDATE source_revisions SET state = 'indexed', indexed_at = now(), error = NULL,"
        " metadata = (metadata - 'embed_error') || %s WHERE id = %s",
        (Jsonb(metadata), revision_id),
    )
    await conn.execute(
        "UPDATE sources SET current_revision_id = %s, title = %s WHERE id = %s",
        (revision_id, title, source_id),
    )


async def mark_index_failed(conn: AsyncConnection, source_id: UUID) -> None:
    await conn.execute(
        "UPDATE source_revisions SET state = 'failed', error = 'index_error'"
        " WHERE source_id = %s AND state = 'pending'",
        (source_id,),
    )


async def default_space(conn: AsyncConnection) -> tuple[int, str, int]:
    cur = await conn.execute("SELECT id, model, dims FROM embedding_spaces WHERE is_default")
    row = await cur.fetchone()
    if row is None:
        raise RuntimeError("no default embedding space")
    return row[0], row[1], row[2]


@dataclass(frozen=True)
class EmbedTarget:
    title: str
    is_current: bool


async def revision_for_embedding(conn: AsyncConnection, revision_id: UUID) -> EmbedTarget | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT s.title, (s.current_revision_id = r.id AND s.deleted_at IS NULL) AS is_current"
            " FROM source_revisions r JOIN sources s ON s.id = r.source_id WHERE r.id = %s",
            (revision_id,),
        )
        row = await cur.fetchone()
    return EmbedTarget(row["title"] or "", bool(row["is_current"])) if row else None


async def chunks_to_embed(
    conn: AsyncConnection, revision_id: UUID, space_id: int
) -> list[tuple[UUID, list[str], str]]:
    cur = await conn.execute(
        "SELECT c.id, c.heading_path, c.content FROM chunks c"
        " LEFT JOIN chunk_embeddings e ON e.chunk_id = c.id AND e.space_id = %s"
        " WHERE c.revision_id = %s AND e.chunk_id IS NULL ORDER BY c.ordinal",
        (space_id, revision_id),
    )
    return [(row[0], list(row[1]), row[2]) for row in await cur.fetchall()]


async def write_embeddings(
    conn: AsyncConnection, space_id: int, rows: Sequence[tuple[UUID, list[float]]]
) -> None:
    async with conn.cursor() as cur:
        await cur.executemany(
            "INSERT INTO chunk_embeddings (chunk_id, space_id, embedding)"
            " VALUES (%s, %s, %s::halfvec)"
            " ON CONFLICT DO NOTHING",
            [
                (chunk_id, space_id, "[" + ",".join(repr(v) for v in vector) + "]")
                for chunk_id, vector in rows
            ],
        )


async def set_embed_error(conn: AsyncConnection, revision_id: UUID, code: str) -> None:
    await conn.execute(
        "UPDATE source_revisions"
        " SET metadata = metadata || jsonb_build_object('embed_error', %s::text) WHERE id = %s",
        (code, revision_id),
    )


async def clear_embed_error(conn: AsyncConnection, revision_id: UUID) -> None:
    await conn.execute(
        "UPDATE source_revisions SET metadata = metadata - 'embed_error' WHERE id = %s",
        (revision_id,),
    )


@dataclass(frozen=True)
class LiveSource:
    source_id: UUID
    current_hash: bytes | None
    size: int | None
    mtime_ns: int | None


async def live_sources(conn: AsyncConnection) -> dict[str, LiveSource]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT s.id, s.external_ref, r.content_hash,"
            " (r.metadata->>'size')::bigint AS size, (r.metadata->>'mtime_ns')::bigint AS mtime_ns"
            " FROM sources s LEFT JOIN LATERAL ("
            "   SELECT content_hash, metadata FROM source_revisions x WHERE x.source_id = s.id"
            "   ORDER BY observed_at DESC LIMIT 1) r ON true"
            " WHERE s.kind = 'obsidian' AND s.deleted_at IS NULL"
        )
        rows = await cur.fetchall()
    return {
        r["external_ref"]: LiveSource(
            r["id"],
            bytes(r["content_hash"]) if r["content_hash"] else None,
            r["size"],
            r["mtime_ns"],
        )
        for r in rows
    }


async def tombstone(conn: AsyncConnection, source_id: UUID) -> None:
    await conn.execute(
        "DELETE FROM chunks WHERE revision_id ="
        " (SELECT current_revision_id FROM sources WHERE id = %s)",
        (source_id,),
    )
    await conn.execute("UPDATE sources SET deleted_at = now() WHERE id = %s", (source_id,))


async def path_taken(conn: AsyncConnection, rel: str) -> bool:
    cur = await conn.execute(
        "SELECT 1 FROM sources WHERE kind = 'obsidian' AND external_ref = %s", (rel,)
    )
    return await cur.fetchone() is not None


async def move_source(conn: AsyncConnection, source_id: UUID, new_rel: str) -> None:
    await conn.execute(
        "UPDATE sources SET external_ref = %s, deleted_at = NULL WHERE id = %s",
        (new_rel, source_id),
    )


async def pending_sources(conn: AsyncConnection) -> list[UUID]:
    cur = await conn.execute(
        "SELECT DISTINCT r.source_id FROM source_revisions r JOIN sources s ON s.id = r.source_id"
        " WHERE r.state = 'pending' AND s.deleted_at IS NULL"
    )
    return [row[0] for row in await cur.fetchall()]


async def revisions_missing_embeddings(conn: AsyncConnection, space_id: int) -> list[UUID]:
    cur = await conn.execute(
        "SELECT r.id FROM sources s JOIN source_revisions r ON r.id = s.current_revision_id"
        " WHERE s.deleted_at IS NULL AND r.state = 'indexed'"
        " AND coalesce(r.metadata->>'embed_error', '') <> 'embed_bad_response'"
        " AND EXISTS (SELECT 1 FROM chunks c LEFT JOIN chunk_embeddings e"
        "   ON e.chunk_id = c.id AND e.space_id = %s"
        "   WHERE c.revision_id = r.id AND e.chunk_id IS NULL)",
        (space_id,),
    )
    return [row[0] for row in await cur.fetchall()]


async def start_run(conn: AsyncConnection, trigger: str) -> int:
    cur = await conn.execute(
        "INSERT INTO ingest_runs (trigger, started_at) VALUES (%s, now()) RETURNING id", (trigger,)
    )
    row = await cur.fetchone()
    if row is None:
        raise RuntimeError("ingest run was not created")
    return row[0]


async def finish_run(
    conn: AsyncConnection, run_id: int, outcome: str, counts: dict[str, int]
) -> None:
    await conn.execute(
        "UPDATE ingest_runs SET finished_at = now(), outcome = %s, counts = %s WHERE id = %s",
        (outcome, Jsonb(counts), run_id),
    )

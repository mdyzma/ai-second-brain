"""Read models for the Sources API and CLI."""

import base64
import binascii
from collections import Counter
from typing import Any, Literal, LiteralString
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from ai_second_brain.config import Settings

PAGE = 50
STATE_SQL = "CASE WHEN s.deleted_at IS NOT NULL THEN 'deleted' ELSE lr.state::text END"


def encode_cursor(ref: str) -> str:
    return base64.urlsafe_b64encode(ref.encode()).decode().rstrip("=")


class InvalidCursorError(ValueError):
    """The cursor isn't one this API issued."""


def decode_cursor(cursor: str) -> str:
    try:
        ref = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
    except (binascii.Error, UnicodeDecodeError) as error:
        raise InvalidCursorError from error
    if not ref or "\x00" in ref:
        raise InvalidCursorError
    return ref


def like_pattern(q: str) -> str:
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def _one(
    conn: AsyncConnection, sql: LiteralString, params: tuple[Any, ...] = ()
) -> dict[str, Any]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, params)
        row = await cur.fetchone()
    return row or {}


async def summary(
    conn: AsyncConnection, settings: Settings, space_id: int, host_reachable: bool | None
) -> dict[str, Any]:
    vault = settings.vault_path
    readable = bool(vault and vault.is_dir())
    sources = await _one(
        conn,
        "SELECT count(*) FILTER (WHERE deleted_at IS NULL) AS active, count(*) FILTER (WHERE deleted_at IS NOT NULL) AS deleted FROM sources",
    )
    revisions = await _one(
        conn,
        "SELECT count(*) FILTER (WHERE lr.state = 'pending') AS pending,"
        " count(*) FILTER (WHERE lr.state = 'indexed') AS indexed,"
        " count(*) FILTER (WHERE lr.state = 'failed') AS failed"
        " FROM sources s JOIN LATERAL (SELECT state FROM source_revisions r WHERE r.source_id = s.id"
        " ORDER BY observed_at DESC, id DESC LIMIT 1) lr ON true WHERE s.deleted_at IS NULL",
    )
    embedding = await _one(
        conn,
        "SELECT count(c.id) AS total, count(e.chunk_id) AS embedded FROM sources s"
        " JOIN chunks c ON c.revision_id = s.current_revision_id"
        " LEFT JOIN chunk_embeddings e ON e.chunk_id = c.id AND e.space_id = %s WHERE s.deleted_at IS NULL",
        (space_id,),
    )
    space = await _one(conn, "SELECT model FROM embedding_spaces WHERE id = %s", (space_id,))
    errors_cur = await conn.execute(
        "SELECT r.metadata->>'embed_error' FROM sources s JOIN source_revisions r ON r.id = s.current_revision_id"
        " WHERE s.deleted_at IS NULL AND r.metadata ? 'embed_error'"
    )
    errors = Counter(row[0] for row in await errors_cur.fetchall())
    jobs = await _one(
        conn,
        "SELECT count(*) FILTER (WHERE status IN ('todo', 'doing')) AS waiting,"
        " count(*) FILTER (WHERE status = 'failed') AS failed FROM procrastinate_jobs WHERE queue_name IN ('ingest', 'embed')",
    )
    last = await _one(
        conn,
        "SELECT trigger, started_at, finished_at, outcome, counts FROM ingest_runs ORDER BY id DESC LIMIT 1",
    )
    return {
        "vault": {"configured": vault is not None, "readable": readable},
        "sources": {"active": sources["active"], "deleted": sources["deleted"]},
        "revisions": {k: revisions.get(k) or 0 for k in ("pending", "indexed", "failed")},
        "chunks": embedding.get("total") or 0,
        "embedding": {
            "model": space.get("model", settings.embed_model),
            "embedded": embedding.get("embedded") or 0,
            "total": embedding.get("total") or 0,
            "host_reachable": host_reachable,
            "last_error": errors.most_common(1)[0][0] if errors else None,
        },
        "jobs": {"waiting": jobs.get("waiting") or 0, "failed": jobs.get("failed") or 0},
        "last_run": last or None,
    }


async def list_sources(
    conn: AsyncConnection, space_id: int, *, state: str | None, q: str | None, cursor: str | None
) -> dict[str, Any]:
    after = decode_cursor(cursor) if cursor else None
    pattern = like_pattern(q) if q else None
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            f"SELECT * FROM (SELECT s.id, s.title, s.external_ref AS path, {STATE_SQL} AS state,"  # noqa: S608
            " coalesce(lr.error, cur.metadata->>'embed_error') AS error, cur.indexed_at,"
            " (SELECT count(*) FROM chunks c WHERE c.revision_id = s.current_revision_id AND s.deleted_at IS NULL) AS chunks,"
            " (SELECT count(*) FROM chunks c JOIN chunk_embeddings e ON e.chunk_id = c.id AND e.space_id = %(space)s"
            "   WHERE c.revision_id = s.current_revision_id AND s.deleted_at IS NULL) AS embedded"
            " FROM sources s LEFT JOIN source_revisions cur ON cur.id = s.current_revision_id"
            " LEFT JOIN LATERAL (SELECT state, error FROM source_revisions r WHERE r.source_id = s.id"
            "   ORDER BY observed_at DESC, id DESC LIMIT 1) lr ON true) x"
            " WHERE (%(state)s::text IS NULL OR x.state = %(state)s)"
            " AND (%(pattern)s::text IS NULL OR x.path ILIKE %(pattern)s ESCAPE '\\' OR x.title ILIKE %(pattern)s ESCAPE '\\')"
            ' AND (%(after)s::text IS NULL OR x.path COLLATE "C" > %(after)s COLLATE "C")'
            ' ORDER BY x.path COLLATE "C" LIMIT %(limit)s',
            {
                "space": space_id,
                "state": state,
                "pattern": pattern,
                "after": after,
                "limit": PAGE + 1,
            },
        )
        rows = await cur.fetchall()
    items, more = rows[:PAGE], len(rows) > PAGE
    return {"items": items, "next_cursor": encode_cursor(items[-1]["path"]) if more else None}


RetryKind = Literal["index", "embed", "none", "missing"]


async def retry_source(
    conn: AsyncConnection, source_id: UUID, space_id: int
) -> tuple[RetryKind, UUID | None]:
    """Returns what to queue: ('index', None), ('embed', current_revision_id), ('none'|'missing', None)."""
    row = await _one(
        conn,
        "SELECT s.current_revision_id, s.deleted_at, lr.id AS latest_id, lr.state, lr.error"
        " FROM sources s"
        " LEFT JOIN LATERAL (SELECT id, state, error FROM source_revisions r WHERE r.source_id = s.id"
        " ORDER BY observed_at DESC, id DESC LIMIT 1) lr ON true WHERE s.id = %s",
        (source_id,),
    )
    if not row:
        return "missing", None
    if row["deleted_at"] is not None:
        return "none", None
    if row["state"] == "failed":
        if row["error"] != "index_error":
            return "none", None  # too_large/encoding: only a changed file can fix it
        await conn.execute(
            "UPDATE source_revisions SET state = 'pending', error = NULL WHERE id = %s",
            (row["latest_id"],),
        )
        return "index", None
    current = row["current_revision_id"]
    if current is None:
        return "none", None
    missing = await _one(
        conn,
        "SELECT count(*) AS n FROM chunks c LEFT JOIN chunk_embeddings e ON e.chunk_id = c.id AND e.space_id = %s"
        " WHERE c.revision_id = %s AND e.chunk_id IS NULL",
        (space_id, current),
    )
    if missing.get("n"):
        await conn.execute(
            "UPDATE source_revisions SET metadata = metadata - 'embed_error' WHERE id = %s",
            (current,),
        )
        return "embed", current
    return "none", None

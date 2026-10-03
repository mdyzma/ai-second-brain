"""Read-side graph queries: status counts, revisions to extract, review lists, entity pages.

Effective visibility (spec §4): on entity pages and in note counts an edge counts only when
the edge is ``accepted``, its entity (both entities, for an entity-to-entity edge) is
``accepted``, and, for a note edge, the note is live (``deleted_at IS NULL``).

Cursors are opaque: the 2a base64 helper around a small JSON list of the sort key.
"""

import json
import logging
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row

from ai_second_brain.graph.schema import ENTITY_TYPES
from ai_second_brain.knowledge.jobs import EXTRACT_QUEUE
from ai_second_brain.knowledge.queue import JobQueue
from ai_second_brain.knowledge.status import (
    InvalidCursorError,
    decode_cursor,
    encode_cursor,
    like_pattern,
)
from ai_second_brain.search.links import obsidian_url

logger = logging.getLogger("ai_second_brain.graph")
STATUSES = ("proposed", "accepted", "rejected")

REVIEW_PAGE = 20
SAMPLES = 3
LINK_PAGE = 50
ENTITY_PAGE = 50
NOTES_CAP = 200

# Current revisions of live sources, each with its extraction row (if any) for one version.
_LIVE = (
    "FROM sources s LEFT JOIN extractions e"
    " ON e.revision_id = s.current_revision_id AND e.extractor_version = %s"
    " WHERE s.deleted_at IS NULL AND s.current_revision_id IS NOT NULL"
)


async def graph_status(conn: AsyncConnection, version: str) -> dict[str, Any]:
    """Spec section 8 `graphStatus`, minus the model and availability.

    ``revisions`` covers the current revisions of live notes at ``version``.
    ``entities.<type>.<status>`` are raw entity-row counts by the entity's own status
    (edge visibility does not apply to them). ``queued`` counts the extract jobs that are
    waiting or running.
    """
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
    cur = await conn.execute(
        "SELECT count(*) FROM procrastinate_jobs"
        " WHERE queue_name = %s AND status IN ('todo', 'doing')",
        (EXTRACT_QUEUE,),
    )
    queued = await cur.fetchone()
    return {
        "extractor_version": version,
        "revisions": {
            "total": total,
            "extracted": extracted,
            "failed": failed,
            "pending": total - extracted - failed,
        },
        "entities": entities,
        "queued": int(queued[0]) if queued else 0,
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


# --- cursors ---------------------------------------------------------------------------------


def _cursor(*parts: Any) -> str:
    values = [p.isoformat() if isinstance(p, datetime) else p for p in parts]
    return encode_cursor(json.dumps(values))


def _uncursor(cursor: str, n: int) -> list[Any]:
    try:
        parts = json.loads(decode_cursor(cursor))
    except ValueError as error:  # JSONDecodeError is a ValueError
        raise InvalidCursorError from error
    if not isinstance(parts, list) or len(parts) != n:
        raise InvalidCursorError
    return parts


def _time_id_cursor(cursor: str | None) -> tuple[datetime | None, UUID | None]:
    if cursor is None:
        return None, None
    at, ident = _uncursor(cursor, 2)
    if not isinstance(at, str) or not isinstance(ident, str):
        raise InvalidCursorError
    try:
        return datetime.fromisoformat(at), UUID(ident)
    except ValueError as error:
        raise InvalidCursorError from error


def _heading(text: str | None) -> str | None:
    """The evidence heading: the last element of the chunk's heading_path, or None."""
    return text or None


def _ref(row: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    return {"id": row[f"{prefix}id"], "name": row[f"{prefix}name"], "type": row[f"{prefix}type"]}


def _refs(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_ref(r) for r in rows]


# The summary of a note's current revision (its latest ok extraction), as a LATERAL join on s.
_SUMMARY = (
    " LEFT JOIN LATERAL (SELECT x.summary FROM extractions x"
    " WHERE x.revision_id = s.current_revision_id AND x.status = 'ok'"
    " ORDER BY x.attempted_at DESC LIMIT 1) ex ON true"
)


# --- review: entities ------------------------------------------------------------------------


async def review_entities(
    conn: AsyncConnection,
    *,
    type: str | None,  # noqa: A002
    cursor: str | None,
    space_id: int,
    min_similarity: float,
    vault_name: str,
) -> dict[str, Any]:
    """Proposed entities, oldest first, with up to 3 sample notes and a merge suggestion.

    The suggestion is the nearest accepted entity of the same type by name embedding, when
    the similarity reaches ``min_similarity``; no embedding yet means no suggestion.
    """
    after_at, after_id = _time_id_cursor(cursor)
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT e.id, e.type::text AS type, e.name, e.created_at,"
            " ARRAY(SELECT DISTINCT ON (a.norm_alias) a.alias FROM entity_aliases a"
            "  WHERE a.entity_id = e.id AND a.norm_alias <> e.norm_name"
            "  ORDER BY a.norm_alias, a.alias) AS aliases,"
            " (SELECT count(DISTINCT g.src_id) FROM edges g JOIN sources s ON s.id = g.src_id"
            "  WHERE g.src_type = 'source' AND g.dst_entity_id = e.id AND g.status <> 'rejected'"
            "  AND s.deleted_at IS NULL) AS mention_count,"
            " sug.id AS sug_id, sug.name AS sug_name, sug.similarity AS sug_similarity"
            " FROM entities e"
            " LEFT JOIN entity_embeddings me ON me.entity_id = e.id AND me.space_id = %(space)s"
            " LEFT JOIN LATERAL (SELECT o.id, o.name,"
            "  1 - (oe.embedding <=> me.embedding) AS similarity"
            "  FROM entity_embeddings oe JOIN entities o ON o.id = oe.entity_id"
            "  WHERE oe.space_id = %(space)s AND o.type = e.type AND o.status = 'accepted'"
            "  AND o.id <> e.id"
            "  ORDER BY oe.embedding <=> me.embedding, o.id LIMIT 1) sug"
            "  ON me.entity_id IS NOT NULL AND sug.similarity >= %(min)s"
            " WHERE e.status = 'proposed'"
            " AND (%(type)s::text IS NULL OR e.type = %(type)s::entity_type)"
            " AND (%(at)s::timestamptz IS NULL"
            "  OR (e.created_at, e.id) > (%(at)s::timestamptz, %(id)s::uuid))"
            " ORDER BY e.created_at, e.id LIMIT %(limit)s",
            {
                "space": space_id,
                "min": min_similarity,
                "type": type,
                "at": after_at,
                "id": after_id,
                "limit": REVIEW_PAGE + 1,
            },
        )
        rows = await cur.fetchall()
        page, more = rows[:REVIEW_PAGE], len(rows) > REVIEW_PAGE
        samples: dict[UUID, list[dict[str, Any]]] = {r["id"]: [] for r in page}
        if page:
            await cur.execute(
                "SELECT * FROM (SELECT g.dst_entity_id AS entity_id, s.external_ref AS path,"  # noqa: S608
                " s.title, ex.summary, row_number() OVER (PARTITION BY g.dst_entity_id"
                '  ORDER BY g.created_at DESC, s.external_ref COLLATE "C") AS n'
                " FROM edges g JOIN sources s ON s.id = g.src_id" + _SUMMARY + ""
                " WHERE g.src_type = 'source' AND g.dst_entity_id = ANY(%s)"
                " AND g.status <> 'rejected' AND s.deleted_at IS NULL) x"
                " WHERE x.n <= %s ORDER BY x.entity_id, x.n",
                (list(samples), SAMPLES),
            )
            for row in await cur.fetchall():
                samples[row["entity_id"]].append(
                    {
                        "path": row["path"],
                        "title": row["title"],
                        "summary": row["summary"],
                        "obsidian_url": obsidian_url(vault_name, row["path"]),
                    }
                )
    items = [
        {
            "id": r["id"],
            "name": r["name"],
            "type": r["type"],
            "aliases": list(r["aliases"]),
            "mention_count": int(r["mention_count"]),
            "samples": samples[r["id"]],
            "suggestion": (
                {"id": r["sug_id"], "name": r["sug_name"], "similarity": float(r["sug_similarity"])}
                if r["sug_id"] is not None
                else None
            ),
        }
        for r in page
    ]
    last = page[-1] if more else None
    return {
        "items": items,
        "next_cursor": _cursor(last["created_at"], str(last["id"])) if last else None,
    }


# --- review: links ---------------------------------------------------------------------------


async def review_links(
    conn: AsyncConnection, *, cursor: str | None, vault_name: str
) -> dict[str, Any]:
    """Proposed links, oldest first.

    Entity-to-entity edges whose two entities are both not rejected, and whose producing
    note (if any) is not tombstoned (kind ``relation``), and mention/about edges from a live
    note to an accepted entity (kind ``mention``). Evidence is the evidence chunk's note and
    heading, else the note that produced the edge.
    """
    after_at, after_id = _time_id_cursor(cursor)
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT g.id, g.src_type, g.relation, g.confidence, g.created_at,"
            " d.id AS dst_id, d.name AS dst_name, d.type::text AS dst_type,"
            " se.id AS se_id, se.name AS se_name, se.type::text AS se_type,"
            " ns.id AS note_id, ns.external_ref AS note_path, ns.title AS note_title,"
            " c.heading_path[cardinality(c.heading_path)] AS ev_heading,"
            " evs.external_ref AS ev_path"
            " FROM edges g JOIN entities d ON d.id = g.dst_entity_id"
            " LEFT JOIN entities se ON g.src_type = 'entity' AND se.id = g.src_id"
            " LEFT JOIN sources ns ON g.src_type = 'source' AND ns.id = g.src_id"
            " LEFT JOIN chunks c ON c.id = g.evidence_chunk_id"
            " LEFT JOIN source_revisions er ON er.id = coalesce(c.revision_id, g.revision_id)"
            " LEFT JOIN sources evs ON evs.id = coalesce(er.source_id, ns.id)"
            "  AND evs.deleted_at IS NULL"
            " WHERE g.status = 'proposed' AND ("
            "  (g.src_type = 'entity' AND d.status <> 'rejected' AND se.status <> 'rejected'"
            # hidden while the note that produced it is tombstoned
            "   AND NOT EXISTS (SELECT 1 FROM source_revisions pr"
            "    JOIN sources ps ON ps.id = pr.source_id"
            "    WHERE pr.id = g.revision_id AND ps.deleted_at IS NOT NULL))"
            "  OR (g.src_type = 'source' AND g.relation IN ('mentions', 'about')"
            "   AND d.status = 'accepted' AND ns.deleted_at IS NULL))"
            " AND (%(at)s::timestamptz IS NULL"
            "  OR (g.created_at, g.id) > (%(at)s::timestamptz, %(id)s::uuid))"
            " ORDER BY g.created_at, g.id LIMIT %(limit)s",
            {"at": after_at, "id": after_id, "limit": LINK_PAGE + 1},
        )
        rows = await cur.fetchall()
    page, more = rows[:LINK_PAGE], len(rows) > LINK_PAGE
    items: list[dict[str, Any]] = []
    for r in page:
        is_relation = r["src_type"] == "entity"
        note = {"source_id": r["note_id"], "path": r["note_path"], "title": r["note_title"]}
        evidence = None
        if r["ev_path"] is not None:
            evidence = {
                "path": r["ev_path"],
                "heading": _heading(r["ev_heading"]),
                "obsidian_url": obsidian_url(vault_name, r["ev_path"]),
            }
        items.append(
            {
                "id": r["id"],
                "kind": "relation" if is_relation else "mention",
                "subject": _ref(r, "se_") if is_relation else None,
                "note": None if is_relation else note,
                "relation": r["relation"],
                "object": _ref(r, "dst_"),
                "confidence": float(r["confidence"]),
                "evidence": evidence,
            }
        )
    last = page[-1] if more else None
    return {
        "items": items,
        "next_cursor": _cursor(last["created_at"], str(last["id"])) if last else None,
    }


# --- entities --------------------------------------------------------------------------------

# Effective note count of entity e (spec §4); callers only count it for accepted entities.
_NOTE_COUNT = (
    "(SELECT count(DISTINCT g.src_id) FROM edges g JOIN sources s ON s.id = g.src_id"
    " WHERE g.src_type = 'source' AND g.dst_entity_id = e.id AND g.status = 'accepted'"
    " AND s.deleted_at IS NULL)"
)


def _list_cursor(cursor: str | None) -> tuple[int, str, UUID] | None:
    if cursor is None:
        return None
    count, name, ident = _uncursor(cursor, 3)
    if type(count) is not int or not isinstance(name, str) or not isinstance(ident, str):
        raise InvalidCursorError
    try:
        return count, name, UUID(ident)
    except ValueError as error:
        raise InvalidCursorError from error


async def list_entities(
    conn: AsyncConnection,
    *,
    type: str | None,  # noqa: A002
    q: str | None,
    cursor: str | None,
) -> dict[str, Any]:
    """Accepted entities by effective note count (desc), then name; ``q`` matches name/aliases."""
    after = _list_cursor(cursor)
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT * FROM (SELECT e.id, e.name, e.type::text AS type,"  # noqa: S608
            " " + _NOTE_COUNT + " AS note_count FROM entities e"
            " WHERE e.status = 'accepted'"
            " AND (%(type)s::text IS NULL OR e.type = %(type)s::entity_type)"
            " AND (%(pattern)s::text IS NULL OR e.name ILIKE %(pattern)s ESCAPE '\\'"
            "  OR EXISTS (SELECT 1 FROM entity_aliases a WHERE a.entity_id = e.id"
            "  AND a.alias ILIKE %(pattern)s ESCAPE '\\'))) x"
            " WHERE %(count)s::bigint IS NULL OR x.note_count < %(count)s::bigint"
            "  OR (x.note_count = %(count)s::bigint"
            '  AND (x.name COLLATE "C", x.id) > (%(name)s::text COLLATE "C", %(id)s::uuid))'
            ' ORDER BY x.note_count DESC, x.name COLLATE "C", x.id LIMIT %(limit)s',
            {
                "type": type,
                "pattern": like_pattern(q) if q else None,
                "count": after[0] if after else None,
                "name": after[1] if after else None,
                "id": after[2] if after else None,
                "limit": ENTITY_PAGE + 1,
            },
        )
        rows = await cur.fetchall()
    page, more = rows[:ENTITY_PAGE], len(rows) > ENTITY_PAGE
    items = [{**r, "note_count": int(r["note_count"])} for r in page]
    last = items[-1] if more else None
    return {
        "items": items,
        "next_cursor": _cursor(last["note_count"], last["name"], str(last["id"])) if last else None,
    }


async def get_entity(
    conn: AsyncConnection, entity_id: UUID, *, vault_name: str
) -> dict[str, Any] | None:
    """One entity with its visible parent, children, related entities and notes; None if unknown.

    The parent and the children show only when the parent link is accepted and both entities
    are accepted. Related entities and notes follow effective visibility, so an entity that
    is not accepted shows none. Notes are newest first (by the note's current revision),
    one row per note (an ``about`` edge outranks ``mentions``), capped at 200.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT e.id, e.name, e.type::text AS type, e.status::text AS status,"
            " ARRAY(SELECT DISTINCT ON (a.norm_alias) a.alias FROM entity_aliases a"
            "  WHERE a.entity_id = e.id AND a.norm_alias <> e.norm_name"
            "  ORDER BY a.norm_alias, a.alias) AS aliases,"
            " p.id AS p_id, p.name AS p_name, p.type::text AS p_type"
            " FROM entities e LEFT JOIN entities p ON p.id = e.parent_id"
            "  AND e.status = 'accepted' AND e.parent_status = 'accepted'"
            "  AND p.status = 'accepted'"
            " WHERE e.id = %s",
            (entity_id,),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        children: list[dict[str, Any]] = []
        related: list[dict[str, Any]] = []
        notes: list[dict[str, Any]] = []
        if row["status"] == "accepted":
            await cur.execute(
                "SELECT id, name, type::text AS type FROM entities"
                " WHERE parent_id = %s AND parent_status = 'accepted' AND status = 'accepted'"
                ' ORDER BY name COLLATE "C", id',
                (entity_id,),
            )
            children = _refs(await cur.fetchall())
            await cur.execute(
                "SELECT g.relation, CASE WHEN g.src_id = %(id)s THEN 'out' ELSE 'in' END"
                " AS direction, o.id, o.name, o.type::text AS type"
                " FROM edges g JOIN entities o ON o.id ="
                "  CASE WHEN g.src_id = %(id)s THEN g.dst_entity_id ELSE g.src_id END"
                " WHERE g.src_type = 'entity' AND g.status = 'accepted' AND o.status = 'accepted'"
                " AND (g.src_id = %(id)s OR g.dst_entity_id = %(id)s)"
                ' ORDER BY g.relation, direction DESC, o.name COLLATE "C", o.id',
                {"id": entity_id},
            )
            related = [
                {"relation": r["relation"], "direction": r["direction"], "entity": _ref(r)}
                for r in await cur.fetchall()
            ]
            await cur.execute(
                "SELECT * FROM (SELECT DISTINCT ON (s.id) s.id AS source_id,"  # noqa: S608
                " s.external_ref AS path, s.title, ex.summary,"
                " c.heading_path[cardinality(c.heading_path)] AS heading, g.relation,"
                " r.observed_at"
                " FROM edges g JOIN sources s ON s.id = g.src_id"
                " LEFT JOIN source_revisions r ON r.id = s.current_revision_id"
                " LEFT JOIN chunks c ON c.id = g.evidence_chunk_id" + _SUMMARY + ""
                " WHERE g.src_type = 'source' AND g.dst_entity_id = %s"
                " AND g.status = 'accepted' AND s.deleted_at IS NULL"
                " ORDER BY s.id, (g.relation = 'about') DESC) n"
                ' ORDER BY n.observed_at DESC NULLS LAST, n.path COLLATE "C" LIMIT %s',
                (entity_id, NOTES_CAP),
            )
            notes = [
                {
                    "source_id": r["source_id"],
                    "path": r["path"],
                    "title": r["title"],
                    "summary": r["summary"],
                    "heading": _heading(r["heading"]),
                    "relation": r["relation"],
                    "obsidian_url": obsidian_url(vault_name, r["path"]),
                }
                for r in await cur.fetchall()
            ]
    return {
        "id": row["id"],
        "name": row["name"],
        "type": row["type"],
        "status": row["status"],
        "aliases": list(row["aliases"]),
        "parent": _ref(row, "p_") if row["p_id"] is not None else None,
        "children": children,
        "related": related,
        "notes": notes,
    }

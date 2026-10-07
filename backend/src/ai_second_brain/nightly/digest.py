"""The morning digest (spec §6): what a nightly run produced and what it read.

Windows: the input window is ``[window_start, started_at)`` (indexed since the previous run),
the output window ``[started_at, out_end)`` with ``out_end = coalesce(finished_at, now())``.
``window_start`` may be ``-infinity``, which the driver cannot load, so it is only ever
compared in SQL and returned only when finite.
"""

import logging
from datetime import date
from typing import Any, LiteralString
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from ai_second_brain.graph.queries import REVIEW_LINK_FROM, REVIEW_LINK_VISIBLE

logger = logging.getLogger("ai_second_brain.nightly")

TOP = 5
FAILED_ITEMS = 10

# The run's bounds as CTE `r`, for the run id parameter %(id)s.
_R: LiteralString = (
    "WITH r AS (SELECT started_at, coalesce(finished_at, now()) AS out_end, window_start"
    " FROM nightly_runs WHERE id = %(id)s)"
)
# The same bounds for the outer run `n` (list_runs).
_RUN_R: LiteralString = "SELECT n.started_at, coalesce(n.finished_at, now()) AS out_end"
# To-review entities (aliased `e`) of the run `r`: still proposed, made in the output window.
_REVIEW_ENTITIES: LiteralString = (
    "FROM entities e, r WHERE e.status = 'proposed'"
    " AND e.created_at >= r.started_at AND e.created_at < r.out_end"
)
# To-review links of the run `r`: what the 4a Links tab lists, made in the output window.
_REVIEW_LINKS: LiteralString = (
    REVIEW_LINK_FROM
    + ", r WHERE "
    + REVIEW_LINK_VISIBLE
    + " AND g.created_at >= r.started_at AND g.created_at < r.out_end"
)
# An entity's confidence: its best mention/about edge from a live note (entities carry none).
_ENTITY_CONFIDENCE: LiteralString = (
    "(SELECT max(m.confidence) FROM edges m JOIN sources ms ON ms.id = m.src_id"
    " AND ms.deleted_at IS NULL WHERE m.src_type = 'source'"
    " AND m.relation IN ('mentions', 'about') AND m.dst_entity_id = e.id)"
)


async def latest_run_id(conn: AsyncConnection) -> UUID | None:
    cur = await conn.execute(
        "SELECT id FROM nightly_runs ORDER BY started_at DESC, id DESC LIMIT 1"
    )
    row = await cur.fetchone()
    return row[0] if row else None


async def run_id_for_date(conn: AsyncConnection, run_date: date) -> UUID | None:
    """The latest run on that local date."""
    cur = await conn.execute(
        "SELECT id FROM nightly_runs WHERE run_date = %s ORDER BY started_at DESC, id DESC LIMIT 1",
        (run_date,),
    )
    row = await cur.fetchone()
    return row[0] if row else None


async def list_runs(conn: AsyncConnection, limit: int) -> list[dict[str, Any]]:
    """Newest first, each with its `remaining` (to-review entities plus links)."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT n.id, n.run_date, n.trigger, n.status, n.started_at,"  # noqa: S608 (constant fragments)
            " (WITH r AS (" + _RUN_R + ") SELECT count(*) " + _REVIEW_ENTITIES + ")"
            " + (WITH r AS (" + _RUN_R + ") SELECT count(*) " + _REVIEW_LINKS + ")"
            " AS remaining"
            " FROM nightly_runs n ORDER BY n.started_at DESC, n.id DESC LIMIT %s",
            (limit,),
        )
        rows = await cur.fetchall()
    return [{**r, "remaining": int(r["remaining"])} for r in rows]


async def digest(conn: AsyncConnection, run_id: UUID) -> dict[str, Any] | None:
    """The digest of one run (spec §6.2), or None when there is no such run."""
    logger.debug("digest id=%s", run_id)
    p = {"id": run_id}
    async with conn.cursor(row_factory=dict_row) as cur:
        # Run, with progress: revisions attempted since the start, capped at the queued.
        await cur.execute(
            "SELECT n.id, n.run_date, n.trigger, n.status,"
            " CASE WHEN n.window_start = '-infinity' THEN NULL ELSE n.window_start END"
            "  AS window_start,"
            " n.started_at, n.finished_at, n.queued_new, n.queued_failed, n.timed_out,"
            " n.unavailable, n.error,"
            " least((SELECT count(DISTINCT x.revision_id) FROM extractions x"
            "  WHERE x.attempted_at >= n.started_at"
            "  AND x.attempted_at < coalesce(n.finished_at, now())),"
            "  n.queued_new + n.queued_failed) AS done,"
            " n.window_start = '-infinity' AS since_beginning"
            " FROM nightly_runs n WHERE n.id = %(id)s",
            p,
        )
        run = await cur.fetchone()
        if run is None:
            return None
        since_beginning = bool(run.pop("since_beginning"))
        run["done"] = int(run["done"])

        await cur.execute(
            _R
            + " SELECT e.type::text AS type, count(*) AS n "
            + _REVIEW_ENTITIES
            + " GROUP BY e.type ORDER BY e.type",
            p,
        )
        by_type = {r["type"]: int(r["n"]) for r in await cur.fetchall()}

        # Top entities, each with the live note of its earliest mention/about edge.
        await cur.execute(
            _R + " SELECT t.*, src.title AS source_title, src.external_ref AS source_path"  # noqa: S608
            " FROM (SELECT e.id, e.name, e.type::text AS type, "
            + _ENTITY_CONFIDENCE
            + " AS confidence "
            + _REVIEW_ENTITIES
            + " ORDER BY confidence DESC NULLS LAST, e.name, e.id LIMIT %(top)s) t"
            " LEFT JOIN LATERAL (SELECT s.title, s.external_ref FROM edges m"
            "  JOIN sources s ON s.id = m.src_id AND s.deleted_at IS NULL"
            "  WHERE m.src_type = 'source' AND m.relation IN ('mentions', 'about')"
            "  AND m.dst_entity_id = t.id"
            "  ORDER BY m.created_at, m.id LIMIT 1) src ON true"
            " ORDER BY t.confidence DESC NULLS LAST, t.name, t.id",
            {**p, "top": TOP},
        )
        top_entities = [
            {**r, "confidence": None if r["confidence"] is None else float(r["confidence"])}
            for r in await cur.fetchall()
        ]

        await cur.execute(_R + " SELECT count(*) AS n " + _REVIEW_LINKS, p)
        link_row = await cur.fetchone()
        link_count = int(link_row["n"]) if link_row else 0
        await cur.execute(
            _R + " SELECT g.id, g.src_type, coalesce(se.name, ns.title, ns.external_ref)"
            " AS subject, g.relation, d.name AS object, g.confidence "
            + _REVIEW_LINKS
            + " ORDER BY g.confidence DESC, g.created_at, g.id LIMIT %(top)s",
            {**p, "top": TOP},
        )
        top_links = [
            {
                "id": r["id"],
                "kind": "relation" if r["src_type"] == "entity" else "mention",
                "subject": r["subject"],
                "relation": r["relation"],
                "object": r["object"],
                "confidence": float(r["confidence"]),
            }
            for r in await cur.fetchall()
        ]

        # Failed: in the output window, for a revision still current on a live note.
        await cur.execute(
            _R + " SELECT f.path, f.error, count(*) OVER () AS total FROM ("  # noqa: S608
            " SELECT DISTINCT ON (s.id) s.external_ref AS path, x.error"
            " FROM extractions x JOIN sources s ON s.current_revision_id = x.revision_id"
            "  AND s.deleted_at IS NULL, r"
            " WHERE x.status = 'failed'"
            # not when a later attempt (another extractor version) succeeded
            " AND NOT EXISTS (SELECT 1 FROM extractions k WHERE k.revision_id = x.revision_id"
            "  AND k.status = 'ok' AND k.attempted_at > x.attempted_at)"
            " AND x.attempted_at >= r.started_at AND x.attempted_at < r.out_end"
            " ORDER BY s.id, x.attempted_at DESC) f"
            " ORDER BY f.path LIMIT %(limit)s",
            {**p, "limit": FAILED_ITEMS},
        )
        failed_rows = await cur.fetchall()

        # Indexed, in the input window.
        await cur.execute(
            _R + " SELECT"  # noqa: S608
            " (SELECT count(*) FROM sources s WHERE s.created_at >= r.window_start"
            "  AND s.created_at < r.started_at) AS created,"
            # distinct notes with a new revision here that had an earlier one, except notes
            # created here: a note saved 37 times reads as one change
            " (SELECT count(DISTINCT v.source_id) FROM source_revisions v"
            "  JOIN sources s ON s.id = v.source_id"
            "  WHERE v.observed_at >= r.window_start AND v.observed_at < r.started_at"
            "  AND NOT (s.created_at >= r.window_start AND s.created_at < r.started_at)"
            "  AND EXISTS (SELECT 1 FROM source_revisions o"
            "   WHERE o.source_id = v.source_id AND o.observed_at < v.observed_at)) AS changed,"
            " (SELECT count(*) FROM sources s WHERE s.deleted_at >= r.window_start"
            "  AND s.deleted_at < r.started_at) AS deleted"
            " FROM r",
            p,
        )
        indexed = await cur.fetchone()
        if indexed is None:  # the run row exists, so r has one row
            return None

    entity_count = sum(by_type.values())
    return {
        "run": run,
        "review": {
            "entities": {"count": entity_count, "by_type": by_type, "top": top_entities},
            "links": {"count": link_count, "top": top_links},
            "remaining": entity_count + link_count,
        },
        "failed": {
            "count": int(failed_rows[0]["total"]) if failed_rows else 0,
            "items": [{"path": r["path"], "error": r["error"]} for r in failed_rows],
        },
        "indexed": {
            "created": int(indexed["created"]),
            "changed": int(indexed["changed"]),
            "deleted": int(indexed["deleted"]),
            "since_beginning": since_beginning,
        },
    }

"""The owner's decisions on entities and links (spec §7).

Every function runs inside the caller's transaction (the API wraps each call in one).
Entity rows are locked before any edge is touched, in ascending id order when there are
two, so decisions and the extraction worker never take entity locks crosswise. Decisions
that change the parent tree (``set_parent``, ``merge_entities``) also take one
transaction-scoped advisory lock first, so two concurrent parent changes can't each pass
the cycle check and together build a cycle.

Logs carry ids and codes only, never names or aliases.
"""

import logging
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any, Literal
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row

from ai_second_brain.graph.names import norm
from ai_second_brain.graph.schema import ENTITY_TYPES

logger = logging.getLogger("ai_second_brain.graph")

DecisionCode = Literal["not_found", "name_taken", "parent_cycle", "type_mismatch", "invalid_action"]

MAX_NAME_CHARS = 200
ACCEPT_MIN_CONFIDENCE = 0.5
# One key for every parent-tree change; held to the end of the transaction.
_PARENT_TREE_LOCK = 4_202_610_030

LockMode = Literal["FOR UPDATE", "FOR NO KEY UPDATE"]


class DecisionError(Exception):
    def __init__(self, code: DecisionCode) -> None:
        super().__init__(code)
        self.code: DecisionCode = code


def would_cycle(parents: Mapping[UUID, UUID | None], child: UUID, new_parent: UUID) -> bool:
    """True when making ``new_parent`` the parent of ``child`` would close a loop.

    Walks up from ``new_parent`` through ``parents``; a missing key ends the chain.
    """
    node: UUID | None = new_parent
    seen: set[UUID] = set()
    while node is not None and node not in seen:
        if node == child:
            return True
        seen.add(node)
        node = parents.get(node)
    return False


async def _lock(conn: AsyncConnection, entity_id: UUID, mode: LockMode) -> dict[str, Any]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT id, type::text AS type, name, norm_name, status::text AS status,"  # noqa: S608
            f" parent_id, parent_status::text AS parent_status FROM entities WHERE id = %s {mode}",
            (entity_id,),
        )
        row = await cur.fetchone()
    if row is None:
        raise DecisionError("not_found")
    return row


async def _parent_tree_lock(conn: AsyncConnection) -> None:
    await conn.execute("SELECT pg_advisory_xact_lock(%s)", (_PARENT_TREE_LOCK,))


async def _chain(conn: AsyncConnection, start: UUID) -> dict[UUID, UUID | None]:
    """The parents map for ``start`` and its ancestors only (UNION stops on a loop)."""
    cur = await conn.execute(
        "WITH RECURSIVE chain(id, parent_id) AS ("
        " SELECT id, parent_id FROM entities WHERE id = %s"
        " UNION"
        " SELECT e.id, e.parent_id FROM entities e JOIN chain c ON e.id = c.parent_id"
        ") SELECT id, parent_id FROM chain",
        (start,),
    )
    return {row[0]: row[1] for row in await cur.fetchall()}


async def _taken(conn: AsyncConnection, type_: str, keys: Sequence[str], entity_id: UUID) -> bool:
    """Another entity of ``type_`` already owns one of ``keys`` as its name or an alias."""
    cur = await conn.execute(
        "SELECT 1 FROM entities WHERE type = %(type)s::entity_type AND id <> %(id)s"
        " AND norm_name = ANY(%(keys)s)"
        " UNION ALL"
        " SELECT 1 FROM entity_aliases WHERE type = %(type)s::entity_type"
        " AND entity_id <> %(id)s AND norm_alias = ANY(%(keys)s)"
        " LIMIT 1",
        {"type": type_, "id": entity_id, "keys": list(keys)},
    )
    return await cur.fetchone() is not None


async def accept_entity(conn: AsyncConnection, entity_id: UUID) -> None:
    """Accept the entity and its confident automatic mention/about edges.

    Automatic edges that an earlier entity reject turned ``rejected`` go back to
    ``proposed`` (unless the confident rule accepts them), so reject-then-accept
    undoes the reject, but only when the entity on the edge's other side is not
    itself rejected. User-decided edges are never touched.
    """
    # NO KEY UPDATE: nothing key-like changes, and it doesn't block the FK checks of
    # extraction inserting new edges to this entity (fewer chances to deadlock).
    await _lock(conn, entity_id, "FOR NO KEY UPDATE")
    await conn.execute(
        "UPDATE entities SET status = 'accepted', reviewed_at = now() WHERE id = %s",
        (entity_id,),
    )
    await conn.execute(
        "UPDATE edges SET updated_at = now(), status = CASE"
        " WHEN dst_entity_id = %(id)s AND relation IN ('mentions', 'about')"
        "  AND confidence >= %(min)s THEN 'accepted'::graph_status"
        " ELSE 'proposed'::graph_status END"
        " WHERE decided_by = 'auto'"
        " AND (dst_entity_id = %(id)s OR (src_type = 'entity' AND src_id = %(id)s))"
        " AND ((status = 'rejected' AND NOT EXISTS ("
        # The other endpoint: the src entity for an incoming edge (a note is always
        # fine), else the dst. An edge to a still-rejected neighbour stays rejected.
        "  SELECT 1 FROM entities o WHERE o.status = 'rejected' AND o.id ="
        "   CASE WHEN edges.dst_entity_id = %(id)s"
        "    THEN CASE WHEN edges.src_type = 'entity' THEN edges.src_id END"
        "    ELSE edges.dst_entity_id END))"
        "  OR (status = 'proposed' AND dst_entity_id = %(id)s"
        "  AND relation IN ('mentions', 'about') AND confidence >= %(min)s))",
        {"id": entity_id, "min": ACCEPT_MIN_CONFIDENCE},
    )
    logger.info("decide action=accept entity=%s", entity_id)


async def reject_entity(conn: AsyncConnection, entity_id: UUID) -> None:
    """Reject the entity and every automatic edge to or from it."""
    await _lock(conn, entity_id, "FOR NO KEY UPDATE")
    await conn.execute(
        "UPDATE entities SET status = 'rejected', reviewed_at = now() WHERE id = %s",
        (entity_id,),
    )
    await conn.execute(
        "UPDATE edges SET status = 'rejected', updated_at = now()"
        " WHERE decided_by = 'auto' AND status <> 'rejected'"
        " AND (dst_entity_id = %(id)s OR (src_type = 'entity' AND src_id = %(id)s))",
        {"id": entity_id},
    )
    logger.info("decide action=reject entity=%s", entity_id)


def _has_control(text: str) -> bool:
    """NUL or any other control character, plain whitespace (tab, newline, ...) excepted."""
    return any(unicodedata.category(c) == "Cc" and not c.isspace() for c in text)


def _clean_name(name: str) -> tuple[str, str]:
    display = name.strip()
    key = norm(name)
    if not key or _has_control(name) or len(display) > MAX_NAME_CHARS or len(key) > MAX_NAME_CHARS:
        raise DecisionError("invalid_action")
    return display, key


async def rename_entity(conn: AsyncConnection, entity_id: UUID, name: str) -> None:
    """Rename; the old name becomes an alias. A same-type name or alias clash is name_taken."""
    display, key = _clean_name(name)
    # FOR UPDATE: norm_name is part of a unique key.
    row = await _lock(conn, entity_id, "FOR UPDATE")
    if await _taken(conn, row["type"], [key], entity_id):
        logger.info("decide action=rename entity=%s code=name_taken", entity_id)
        raise DecisionError("name_taken")
    try:
        async with conn.transaction():  # a savepoint: a lost race leaves the caller's tx usable
            # Renaming to one of its own aliases: that alias row is now redundant.
            await conn.execute(
                "DELETE FROM entity_aliases WHERE entity_id = %s AND norm_alias = %s",
                (entity_id, key),
            )
            await conn.execute(
                "UPDATE entities SET name = %s, norm_name = %s WHERE id = %s",
                (display, key, entity_id),
            )
            if row["norm_name"] != key:
                await conn.execute(
                    "INSERT INTO entity_aliases (entity_id, type, alias, norm_alias)"
                    " VALUES (%s, %s::entity_type, %s, %s)"
                    " ON CONFLICT (type, norm_alias) DO NOTHING",
                    (entity_id, row["type"], row["name"], row["norm_name"]),
                )
    except UniqueViolation:
        # A concurrent create_entity took the name after the _taken check.
        logger.info("decide action=rename entity=%s code=name_taken", entity_id)
        raise DecisionError("name_taken") from None
    logger.info("decide action=rename entity=%s", entity_id)


async def retype_entity(conn: AsyncConnection, entity_id: UUID, type: str) -> None:  # noqa: A002
    """Change the type and the alias rows' type.

    A clash of the name or any alias with another entity of the new type is name_taken.
    A parent must share its child's type, so the parent link is cleared unless the
    parent already has the new type. Children keep their link: the tree is the
    owner's to fix, and extraction may already have proposed cross-type parents.
    """
    if type not in ENTITY_TYPES:
        raise DecisionError("invalid_action")
    row = await _lock(conn, entity_id, "FOR UPDATE")  # type is part of a unique key
    if row["type"] == type:
        return
    cur = await conn.execute(
        "SELECT norm_alias FROM entity_aliases WHERE entity_id = %s", (entity_id,)
    )
    keys = [row["norm_name"], *(r[0] for r in await cur.fetchall())]
    if await _taken(conn, type, keys, entity_id):
        logger.info("decide action=retype entity=%s code=name_taken", entity_id)
        raise DecisionError("name_taken")
    keep_parent = False
    if row["parent_id"] is not None:
        cur = await conn.execute(
            "SELECT type::text FROM entities WHERE id = %s", (row["parent_id"],)
        )
        parent = await cur.fetchone()
        keep_parent = parent is not None and parent[0] == type
    try:
        async with conn.transaction():  # a savepoint: a lost race leaves the caller's tx usable
            if keep_parent:
                await conn.execute(
                    "UPDATE entities SET type = %s::entity_type WHERE id = %s", (type, entity_id)
                )
            else:
                await conn.execute(
                    "UPDATE entities SET type = %s::entity_type,"
                    " parent_id = NULL, parent_status = NULL WHERE id = %s",
                    (type, entity_id),
                )
            await conn.execute(
                "UPDATE entity_aliases SET type = %s::entity_type WHERE entity_id = %s",
                (type, entity_id),
            )
    except UniqueViolation:
        # A concurrent create_entity took the name or an alias after the _taken check.
        logger.info("decide action=retype entity=%s code=name_taken", entity_id)
        raise DecisionError("name_taken") from None
    logger.info("decide action=retype entity=%s", entity_id)


async def set_parent(conn: AsyncConnection, entity_id: UUID, parent_id: UUID | None) -> None:
    """Set an accepted parent of the same type, or clear it with ``None``."""
    await _parent_tree_lock(conn)
    row = await _lock(conn, entity_id, "FOR NO KEY UPDATE")
    if parent_id is None:
        await conn.execute(
            "UPDATE entities SET parent_id = NULL, parent_status = NULL WHERE id = %s",
            (entity_id,),
        )
        logger.info("decide action=parent entity=%s cleared", entity_id)
        return
    cur = await conn.execute(
        "SELECT type::text FROM entities WHERE id = %s FOR KEY SHARE", (parent_id,)
    )
    parent = await cur.fetchone()
    if parent is None:
        raise DecisionError("not_found")
    if parent[0] != row["type"]:
        raise DecisionError("type_mismatch")
    if would_cycle(await _chain(conn, parent_id), entity_id, parent_id):
        logger.info("decide action=parent entity=%s code=parent_cycle", entity_id)
        raise DecisionError("parent_cycle")
    await conn.execute(
        "UPDATE entities SET parent_id = %s, parent_status = 'accepted' WHERE id = %s",
        (parent_id, entity_id),
    )
    logger.info("decide action=parent entity=%s parent=%s", entity_id, parent_id)


async def _move_edges(conn: AsyncConnection, loser_id: UUID, into_id: UUID) -> tuple[int, int]:
    """Re-point every edge of the loser at ``into``; returns (moved, dropped).

    On a key clash the user-decided row wins, else the higher confidence (the row
    already on ``into`` wins a tie). Self-loops are dropped.
    """
    moved = dropped = 0
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT id, src_type, src_id, relation, dst_entity_id, decided_by, confidence"
            " FROM edges WHERE dst_entity_id = %(l)s OR (src_type = 'entity' AND src_id = %(l)s)"
            " ORDER BY src_type, src_id, relation, dst_entity_id FOR UPDATE",
            {"l": loser_id},
        )
        edges = await cur.fetchall()
        for edge in edges:
            src_id = (
                into_id
                if edge["src_type"] == "entity" and edge["src_id"] == loser_id
                else edge["src_id"]
            )
            dst_id = into_id if edge["dst_entity_id"] == loser_id else edge["dst_entity_id"]
            if edge["src_type"] == "entity" and src_id == dst_id:
                await cur.execute("DELETE FROM edges WHERE id = %s", (edge["id"],))
                dropped += 1
                continue
            await cur.execute(
                "SELECT id, decided_by, confidence FROM edges WHERE src_type = %s"
                " AND src_id = %s AND relation = %s AND dst_entity_id = %s FOR UPDATE",
                (edge["src_type"], src_id, edge["relation"], dst_id),
            )
            other = await cur.fetchone()
            if other is not None:
                if _rank(edge) > _rank(other):
                    await cur.execute("DELETE FROM edges WHERE id = %s", (other["id"],))
                else:
                    await cur.execute("DELETE FROM edges WHERE id = %s", (edge["id"],))
                    dropped += 1
                    continue
            await cur.execute(
                "UPDATE edges SET src_id = %s, dst_entity_id = %s, updated_at = now()"
                " WHERE id = %s",
                (src_id, dst_id, edge["id"]),
            )
            moved += 1
    return moved, dropped


def _rank(edge: Mapping[str, Any]) -> tuple[bool, float]:
    return edge["decided_by"] == "user", float(edge["confidence"])


async def _carry_parent(
    conn: AsyncConnection, loser: Mapping[str, Any], into: Mapping[str, Any]
) -> None:
    """Give a parentless ``into`` the loser's parent, under set_parent's type and loop rules."""
    parent_id: UUID = loser["parent_id"]
    cur = await conn.execute(
        "SELECT type::text FROM entities WHERE id = %s FOR KEY SHARE", (parent_id,)
    )
    parent = await cur.fetchone()
    if parent is None or parent[0] != into["type"]:
        return
    chain = await _chain(conn, parent_id)
    if loser["id"] in chain or would_cycle(chain, into["id"], parent_id):
        return
    await conn.execute(
        "UPDATE entities SET parent_id = %s, parent_status = %s::graph_status WHERE id = %s",
        (parent_id, loser["parent_status"], into["id"]),
    )


async def merge_entities(conn: AsyncConnection, loser_id: UUID, into_id: UUID) -> UUID:
    """Fold ``loser`` into ``into`` (same type only) and delete it; returns ``into_id``.

    A parentless ``into`` (or one that hung under the loser) takes over the loser's
    parent, with its status, if that parent has the same type and closes no loop.
    The caller queues ``embed_entity(into)`` after the commit if it has no embedding.

    Merge touches many edge rows, so despite the ordered locks it can still lose a
    deadlock (40P01) or serialization failure against a concurrent extraction. The
    API (Task 7) retries such a failure once, then answers ``409 busy``.
    """
    if loser_id == into_id:
        raise DecisionError("invalid_action")
    await _parent_tree_lock(conn)
    # Both rows in ascending id order, so crossing merges can't deadlock.
    locked = {i: await _lock(conn, i, "FOR UPDATE") for i in sorted((loser_id, into_id))}
    loser, into = locked[loser_id], locked[into_id]
    if loser["type"] != into["type"]:
        logger.info("decide action=merge entity=%s into=%s code=type_mismatch", loser_id, into_id)
        raise DecisionError("type_mismatch")

    moved, dropped = await _move_edges(conn, loser_id, into_id)

    # Aliases: the loser's own rows move over (one equal to into's name is redundant
    # and goes with the loser); its name is added unless someone else owns it.
    await conn.execute(
        "UPDATE entity_aliases SET entity_id = %s WHERE entity_id = %s AND norm_alias <> %s",
        (into_id, loser_id, into["norm_name"]),
    )
    if loser["norm_name"] != into["norm_name"]:
        await conn.execute(
            "INSERT INTO entity_aliases (entity_id, type, alias, norm_alias)"
            " VALUES (%s, %s::entity_type, %s, %s) ON CONFLICT (type, norm_alias) DO NOTHING",
            (into_id, into["type"], loser["name"], loser["norm_name"]),
        )

    # Parents: into may not hang under the loser, and no child of the loser that is an
    # ancestor of into may be moved under into (that would close a loop): clear those.
    if into["parent_id"] == loser_id:
        await conn.execute(
            "UPDATE entities SET parent_id = NULL, parent_status = NULL WHERE id = %s",
            (into_id,),
        )
        ancestors: set[UUID] = set()
    else:
        ancestors = set(await _chain(conn, into_id)) - {into_id}
    if ancestors:
        await conn.execute(
            "UPDATE entities SET parent_id = NULL, parent_status = NULL"
            " WHERE parent_id = %s AND id = ANY(%s)",
            (loser_id, list(ancestors)),
        )
    await conn.execute(
        "UPDATE entities SET parent_id = %s WHERE parent_id = %s AND id <> %s",
        (into_id, loser_id, into_id),
    )
    if into["parent_id"] in (None, loser_id) and loser["parent_id"] is not None:
        await _carry_parent(conn, loser, into)

    await conn.execute("DELETE FROM entities WHERE id = %s", (loser_id,))
    logger.info(
        "decide action=merge entity=%s into=%s moved=%d dropped=%d",
        loser_id,
        into_id,
        moved,
        dropped,
    )
    return into_id


async def decide_links(
    conn: AsyncConnection, items: Sequence[tuple[UUID, Literal["accept", "reject"]]]
) -> int:
    """Set each known edge's status as the user's decision; unknown ids are ignored.

    Returns how many edges were updated. A repeated id takes its last action.
    """
    wanted: dict[UUID, str] = {}
    for edge_id, action in items:
        if action not in ("accept", "reject"):
            raise DecisionError("invalid_action")
        wanted[edge_id] = "accepted" if action == "accept" else "rejected"
    if not wanted:
        return 0
    # Lock in key order, the order extraction upserts in.
    await conn.execute(
        "SELECT 1 FROM edges WHERE id = ANY(%s)"
        " ORDER BY src_type, src_id, relation, dst_entity_id FOR UPDATE",
        (list(wanted),),
    )
    cur = await conn.execute(
        "UPDATE edges SET status = v.status::graph_status, decided_by = 'user',"
        " updated_at = now()"
        " FROM unnest(%s::uuid[], %s::text[]) AS v(id, status) WHERE edges.id = v.id",
        (list(wanted), list(wanted.values())),
    )
    count = cur.rowcount
    logger.info("decide action=links requested=%d updated=%d", len(wanted), count)
    return count

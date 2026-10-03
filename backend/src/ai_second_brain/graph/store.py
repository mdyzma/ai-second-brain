"""SQL helpers for the knowledge graph: entities, aliases, embeddings, extractions."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ai_second_brain.graph.names import norm


@dataclass(frozen=True)
class EntityRow:
    id: UUID
    type: str
    name: str
    status: str


@dataclass(frozen=True)
class RevisionInfo:
    source_id: UUID
    title: str
    path: str
    is_current: bool
    live: bool


def _vector(vector: list[float]) -> str:
    return "[" + ",".join(repr(v) for v in vector) + "]"


def _entity(row: dict[str, Any]) -> EntityRow:
    return EntityRow(row["id"], row["type"], row["name"], row["status"])


_ENTITY_COLS = "e.id, e.type::text AS type, e.name, e.status::text AS status"


async def find_by_name(
    conn: AsyncConnection, type: str, norm_name: str
) -> tuple[EntityRow, Literal["exact", "alias"]] | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            f"SELECT {_ENTITY_COLS} FROM entities e WHERE e.type = %s::entity_type"  # noqa: S608
            " AND e.norm_name = %s",
            (type, norm_name),
        )
        row = await cur.fetchone()
        if row is not None:
            return _entity(row), "exact"
        await cur.execute(
            f"SELECT {_ENTITY_COLS} FROM entity_aliases a"  # noqa: S608
            " JOIN entities e ON e.id = a.entity_id"
            " WHERE a.type = %s::entity_type AND a.norm_alias = %s",
            (type, norm_name),
        )
        row = await cur.fetchone()
    return (_entity(row), "alias") if row is not None else None


async def nearest_by_embedding(
    conn: AsyncConnection,
    type: str,
    vector: list[float],
    *,
    space_id: int,
    dims: int,
    min_similarity: float,
) -> tuple[EntityRow, float] | None:
    n = sql.Literal(dims)
    query = sql.SQL(
        "SELECT {cols}, 1 - (ee.embedding::halfvec({n}) <=> %s::halfvec({n})) AS similarity"
        " FROM entity_embeddings ee JOIN entities e ON e.id = ee.entity_id"
        " WHERE e.type = %s::entity_type AND e.status <> 'rejected' AND ee.space_id = %s"
        " ORDER BY ee.embedding::halfvec({n}) <=> %s::halfvec({n}) LIMIT 1"
    ).format(cols=sql.SQL(_ENTITY_COLS), n=n)
    literal = _vector(vector)
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, (literal, type, space_id, literal))
        row = await cur.fetchone()
    if row is None or row["similarity"] < min_similarity:
        return None
    return _entity(row), float(row["similarity"])


async def create_entity(
    conn: AsyncConnection, type: str, name: str, aliases: Sequence[str]
) -> EntityRow:
    norm_name = norm(name)
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "INSERT INTO entities (type, name, norm_name) VALUES (%s::entity_type, %s, %s)"
            " RETURNING id, type::text AS type, name, status::text AS status",
            (type, name, norm_name),
        )
        row = await cur.fetchone()
        if row is None:
            raise RuntimeError("entity insert returned no row")
        entity = _entity(row)
        seen = {norm_name}
        for alias in aliases:
            norm_alias = norm(alias)
            if not norm_alias or norm_alias in seen:
                continue
            seen.add(norm_alias)
            await cur.execute(
                "INSERT INTO entity_aliases (entity_id, type, alias, norm_alias)"
                " VALUES (%s, %s::entity_type, %s, %s) ON CONFLICT (type, norm_alias) DO NOTHING",
                (entity.id, type, alias, norm_alias),
            )
    return entity


async def missing_embedding(conn: AsyncConnection, entity_id: UUID, space_id: int) -> bool:
    cur = await conn.execute(
        "SELECT 1 FROM entity_embeddings WHERE entity_id = %s AND space_id = %s",
        (entity_id, space_id),
    )
    return await cur.fetchone() is None


async def upsert_entity_embedding(
    conn: AsyncConnection, entity_id: UUID, space_id: int, vector: list[float]
) -> None:
    await conn.execute(
        "INSERT INTO entity_embeddings (entity_id, space_id, embedding)"
        " VALUES (%s, %s, %s::halfvec)"
        " ON CONFLICT (entity_id, space_id) DO UPDATE SET embedding = EXCLUDED.embedding",
        (entity_id, space_id, _vector(vector)),
    )


async def record_extraction(
    conn: AsyncConnection,
    revision_id: UUID,
    version: str,
    *,
    status: str,
    model: str,
    summary: str | None = None,
    output: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    await conn.execute(
        "INSERT INTO extractions (revision_id, extractor_version, status, error, model,"
        " summary, output) VALUES (%s, %s, %s, %s, %s, %s, %s)"
        " ON CONFLICT (revision_id, extractor_version) DO UPDATE SET"
        " status = EXCLUDED.status, error = EXCLUDED.error, model = EXCLUDED.model,"
        " summary = EXCLUDED.summary, output = EXCLUDED.output, attempted_at = now()",
        (
            revision_id,
            version,
            status,
            error,
            model,
            summary,
            Jsonb(output) if output is not None else None,
        ),
    )


async def has_ok_extraction(conn: AsyncConnection, revision_id: UUID, version: str) -> bool:
    cur = await conn.execute(
        "SELECT 1 FROM extractions"
        " WHERE revision_id = %s AND extractor_version = %s AND status = 'ok'",
        (revision_id, version),
    )
    return await cur.fetchone() is not None


async def revision_chunks(conn: AsyncConnection, revision_id: UUID) -> list[tuple[UUID, str, str]]:
    cur = await conn.execute(
        "SELECT id, heading_text, content FROM chunks WHERE revision_id = %s ORDER BY ordinal",
        (revision_id,),
    )
    return [(r[0], r[1], r[2]) for r in await cur.fetchall()]


async def revision_info(conn: AsyncConnection, revision_id: UUID) -> RevisionInfo | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT s.id AS source_id, s.title, s.external_ref,"
            " (s.current_revision_id = r.id) AS is_current, (s.deleted_at IS NULL) AS live"
            " FROM source_revisions r JOIN sources s ON s.id = r.source_id WHERE r.id = %s",
            (revision_id,),
        )
        row = await cur.fetchone()
    if row is None:
        return None
    return RevisionInfo(
        row["source_id"],
        row["title"] or "",
        row["external_ref"],
        bool(row["is_current"]),
        bool(row["live"]),
    )

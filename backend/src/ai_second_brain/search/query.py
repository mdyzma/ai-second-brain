"""One hybrid query: FTS ∪ HNSW, fused with reciprocal rank fusion (k = 60)."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row

from ai_second_brain.search.terms import ChatTerms

SPACE_ID = 1
SPACE_DIMS = 1024
RRF_K = 60
LIST_LIMIT = 50
VECTOR_CANDIDATES = 200
Mode = Literal["search", "chat"]
HEADLINE_OPTS = (
    "StartSel=<mark>, StopSel=</mark>, MaxFragments=2, MaxWords=30, MinWords=12,"
    ' FragmentDelimiter=" … "'
)


@dataclass(frozen=True)
class Hit:
    source_id: UUID
    path: str
    title: str | None
    chunk_id: UUID
    heading_path: list[str]
    content: str
    headline: str | None
    score: float
    matched: frozenset[str]
    similarity: float | None


@dataclass(frozen=True)
class SearchResult:
    hits: list[Hit]
    vector_used: bool


def like_prefix(folder: str) -> str:
    escaped = folder.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"{escaped}/%"


def _tsquery_sql(mode: Mode) -> sql.Composable:
    if mode == "search":
        return sql.SQL("websearch_to_tsquery('simple', %(q)s)")
    return sql.SQL("to_tsquery('simple', %(or_query)s)")


_STATEMENT = """
WITH live AS (
  SELECT s.id AS source_id, s.external_ref AS path, s.title, s.current_revision_id AS revision_id
  FROM sources s JOIN source_revisions r ON r.id = s.current_revision_id
  WHERE s.deleted_at IS NULL
    AND (%(folder)s::text IS NULL OR s.external_ref LIKE %(folder)s ESCAPE '\\')
    AND r.tags @> %(tags)s::text[]
),
tsq AS (SELECT {tsquery} AS q WHERE %(has_text)s),
fts AS (
  SELECT c.id AS chunk_id,
         row_number() OVER (ORDER BY ts_rank_cd(c.tsv, tsq.q) DESC, c.id) AS rank
  FROM tsq, chunks c JOIN live l ON l.revision_id = c.revision_id
  WHERE c.tsv @@ tsq.q {chat_rule}
  ORDER BY rank LIMIT {list_limit}
),
candidates AS MATERIALIZED (
  SELECT e.chunk_id, e.embedding::halfvec({dims}) <=> %(vec)s::halfvec({dims}) AS distance
  FROM chunk_embeddings e
  WHERE e.space_id = {space} AND %(vec)s::halfvec IS NOT NULL
  ORDER BY e.embedding::halfvec({dims}) <=> %(vec)s::halfvec({dims})
  LIMIT {candidates}
),
vec AS (
  SELECT k.chunk_id, row_number() OVER (ORDER BY k.distance, k.chunk_id) AS rank,
         1 - k.distance AS similarity
  FROM candidates k JOIN chunks c ON c.id = k.chunk_id JOIN live l ON l.revision_id = c.revision_id
  ORDER BY rank LIMIT {list_limit}
),
fused AS (
  SELECT chunk_id, sum(1.0 / ({k} + rank)) AS score,
         bool_or(src = 'text') AS by_text, bool_or(src = 'vector') AS by_vector,
         max(similarity) AS similarity
  FROM (SELECT chunk_id, rank, 'text' AS src, NULL::float8 AS similarity FROM fts
        UNION ALL SELECT chunk_id, rank, 'vector', similarity FROM vec) u
  GROUP BY chunk_id
),
ranked AS (
  SELECT f.*, c.heading_path, c.content, l.source_id, l.path, l.title,
         row_number() OVER (PARTITION BY l.source_id ORDER BY f.score DESC, c.id) AS per_source
  FROM fused f JOIN chunks c ON c.id = f.chunk_id JOIN live l ON l.revision_id = c.revision_id
)
SELECT r.source_id, r.path, r.title, r.chunk_id, r.heading_path, r.content,
       r.score::float8 AS score, r.by_text, r.by_vector, r.similarity,
       CASE WHEN r.by_text THEN ts_headline(
         'simple',
         replace(replace(replace(r.content, '&', '&amp;'), '<', '&lt;'), '>', '&gt;'),
         (SELECT q FROM tsq), {headline_opts}
       ) END AS headline
FROM ranked r
WHERE r.per_source <= %(per_source)s
ORDER BY r.score DESC, r.path, r.per_source
LIMIT %(limit)s
"""

_CHAT_RULE = """
    AND (
      (SELECT count(*) FROM unnest(%(terms)s::text[]) t
        WHERE c.tsv @@ to_tsquery('simple', quote_literal(t))) >= 2
      OR EXISTS (SELECT 1 FROM unnest(%(identifiers)s::text[]) t
        WHERE c.tsv @@ to_tsquery('simple', quote_literal(t)))
    )
"""


def _or_query(terms: ChatTerms) -> str:
    return " | ".join(f"'{term}'" for term in terms.terms)  # terms are [\w.-] only (terms.py)


async def query(
    conn: AsyncConnection[Any],
    q: str,
    *,
    vector: list[float] | None,
    folder: str | None = None,
    tags: Sequence[str] = (),
    limit: int = 20,
    mode: Mode = "search",
    terms: ChatTerms | None = None,
) -> SearchResult:
    if mode == "chat" and terms is None:
        raise ValueError("chat mode needs terms")
    has_text = bool(q.strip()) if mode == "search" else bool(terms and terms.terms)
    statement = sql.SQL(_STATEMENT).format(
        tsquery=_tsquery_sql(mode),
        chat_rule=sql.SQL(_CHAT_RULE if mode == "chat" else ""),
        list_limit=sql.Literal(LIST_LIMIT),
        candidates=sql.Literal(VECTOR_CANDIDATES),
        dims=sql.Literal(SPACE_DIMS),
        space=sql.Literal(SPACE_ID),
        k=sql.Literal(RRF_K),
        headline_opts=sql.Literal(HEADLINE_OPTS),
    )
    params = {
        "q": q,
        "or_query": _or_query(terms) if terms and terms.terms else "",
        "terms": list(terms.terms) if terms else [],
        "identifiers": list(terms.identifiers) if terms else [],
        "has_text": has_text,
        "folder": like_prefix(folder) if folder else None,
        "tags": list(tags),
        "vec": _vector_literal(vector),
        "per_source": 2 if mode == "chat" else 1,
        "limit": limit,
    }
    async with conn.transaction():
        ef_search = sql.SQL("SET LOCAL hnsw.ef_search = {}").format(sql.Literal(VECTOR_CANDIDATES))
        await conn.execute(ef_search)
        async with conn.cursor(row_factory=dict_row) as cur:
            # prepare=False: psycopg auto-prepares after 5 runs and Postgres then switches to a
            # generic plan, about 4x slower here (the custom plan uses the literal tsquery and
            # vector).
            await cur.execute(statement, params, prepare=False)
            rows = await cur.fetchall()
    hits = [
        Hit(
            source_id=row["source_id"],
            path=row["path"],
            title=row["title"],
            chunk_id=row["chunk_id"],
            heading_path=_trail(row["title"], row["heading_path"]),
            content=row["content"],
            headline=_safe_headline(row["headline"]),
            score=row["score"],
            matched=frozenset(
                n for n, on in (("text", row["by_text"]), ("vector", row["by_vector"])) if on
            ),
            similarity=row["similarity"],
        )
        for row in rows
    ]
    return SearchResult(hits, vector is not None)


def _trail(title: str | None, heading_path: Sequence[str]) -> list[str]:
    parts = list(heading_path)
    return parts[1:] if parts and title is not None and parts[0] == title else parts


def _vector_literal(vector: list[float] | None) -> str | None:
    return None if vector is None else "[" + ",".join(repr(float(v)) for v in vector) + "]"


def _safe_headline(headline: str | None) -> str | None:
    if headline is None:
        return None
    stripped = headline.replace("<mark>", "").replace("</mark>", "")
    return headline if "<" not in stripped and ">" not in stripped else None

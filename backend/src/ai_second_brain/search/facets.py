"""Folder (two levels) and tag counts over live, searchable notes."""

from typing import Any

from psycopg import AsyncConnection

_FOLDERS = """
SELECT folder, count(*) FROM (
  SELECT DISTINCT s.id, f.folder
  FROM sources s
  CROSS JOIN LATERAL (
    SELECT array_to_string((string_to_array(s.external_ref, '/'))[1:n], '/') AS folder
    FROM generate_series(1, least(2, array_length(string_to_array(s.external_ref, '/'), 1) - 1)) n
  ) f
  WHERE s.deleted_at IS NULL AND s.current_revision_id IS NOT NULL
) x GROUP BY folder ORDER BY folder
"""
_TAGS = """
SELECT t, count(*) FROM sources s
JOIN source_revisions r ON r.id = s.current_revision_id
CROSS JOIN LATERAL unnest(r.tags) t
WHERE s.deleted_at IS NULL
GROUP BY t ORDER BY count(*) DESC, t LIMIT 200
"""


async def facets(
    conn: AsyncConnection[Any],
) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    folders = await (await conn.execute(_FOLDERS)).fetchall()
    tags = await (await conn.execute(_TAGS)).fetchall()
    return [(f, n) for f, n in folders], [(t, n) for t, n in tags]

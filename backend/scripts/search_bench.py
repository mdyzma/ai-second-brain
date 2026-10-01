"""p50/p95 of hybrid search over a synthetic 50k-chunk set. Needs an empty scratch database.

Usage: uv run python scripts/search_bench.py postgres://…/scratch_db
"""

import random
import statistics
import sys
import time
from typing import Any, LiteralString

from psycopg import AsyncConnection

from ai_second_brain.runtime import new_event_loop
from ai_second_brain.search.query import query

WORDS = "nas dysk kopia backup proxmox klaster sieć router vlan zfs raid docker host serwer".split()


def vec(rng: random.Random) -> list[float]:
    values = [rng.gauss(0, 1) for _ in range(1024)]
    norm = sum(v * v for v in values) ** 0.5
    return [v / norm for v in values]


async def insert_id(
    conn: AsyncConnection, statement: LiteralString, params: tuple[Any, ...]
) -> Any:
    row = await (await conn.execute(statement, params)).fetchone()
    if row is None:
        raise RuntimeError("insert returned no id")
    return row[0]


async def seed(
    conn: AsyncConnection, rng: random.Random, notes: int = 5000, chunks_per_note: int = 10
) -> None:
    async with conn.transaction():
        for n in range(notes):
            src = await insert_id(
                conn,
                "INSERT INTO sources (kind, external_ref, title)"
                " VALUES ('obsidian', %s, %s) RETURNING id",
                (f"bench/n{n}.md", f"n{n}"),
            )
            rev = await insert_id(
                conn,
                "INSERT INTO source_revisions (source_id, content_hash, raw_text, state, tags)"
                " VALUES (%s, %s, '', 'indexed', %s) RETURNING id",
                (src, rng.randbytes(32), [rng.choice(WORDS)]),
            )
            await conn.execute(
                "UPDATE sources SET current_revision_id = %s WHERE id = %s", (rev, src)
            )
            for c in range(chunks_per_note):
                text = " ".join(rng.choice(WORDS) for _ in range(120)) + f" host{n:05d}"
                chunk = await insert_id(
                    conn,
                    "INSERT INTO chunks (revision_id, ordinal, content)"
                    " VALUES (%s, %s, %s) RETURNING id",
                    (rev, c, text),
                )
                await conn.execute(
                    "INSERT INTO chunk_embeddings (chunk_id, space_id, embedding)"
                    " VALUES (%s, 1, %s::halfvec)",
                    (chunk, str(vec(rng))),
                )


async def main(url: str) -> None:
    rng = random.Random(7)  # noqa: S311 - deterministic synthetic data
    async with await AsyncConnection.connect(url) as conn:
        await seed(conn, rng)
        await conn.execute("ANALYZE")
        await conn.commit()
        timings = []
        for i in range(200):
            q = f"host{rng.randrange(5000):05d}" if i % 2 else " ".join(rng.sample(WORDS, 2))
            started = time.perf_counter()
            await query(conn, q, vector=vec(rng), limit=20)
            timings.append((time.perf_counter() - started) * 1000)
    timings.sort()
    print(f"p50={statistics.median(timings):.1f}ms p95={timings[int(len(timings) * 0.95)]:.1f}ms")


if __name__ == "__main__":
    loop = new_event_loop()
    loop.run_until_complete(main(sys.argv[1]))

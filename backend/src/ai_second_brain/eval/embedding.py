"""Embed the scratch snapshot per model with a resumable cache; time query embeddings."""

import hashlib
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import httpx2
from psycopg import AsyncConnection

from ai_second_brain.config import local_model_name
from ai_second_brain.knowledge.embed_text import embed_input
from ai_second_brain.knowledge.embedder import Embedder, EmbedError

KEEP_ALIVE = "30m"
SPACE_BASE = 100


@dataclass(frozen=True)
class ModelSpace:
    model: str
    space_id: int
    dims: int


class PreflightError(Exception):
    def __init__(self, code: str, model: str) -> None:
        super().__init__(f"{code}: {model}")
        self.code, self.model = code, model


async def preflight(
    make_embedder: Callable[[str], Embedder], models: Sequence[str]
) -> list[ModelSpace]:
    spaces: list[ModelSpace] = []
    for index, model in enumerate(models):
        try:
            local_model_name(model)
        except ValueError:
            raise PreflightError("cloud_model_refused", model) from None
        try:
            [vector] = await make_embedder(model).embed(["preflight"], keep_alive=KEEP_ALIVE)
        except EmbedError as error:
            raise PreflightError(error.code, model) from None
        spaces.append(ModelSpace(model, SPACE_BASE + index, len(vector)))
    return spaces


def _digest(text: str) -> bytes:
    return hashlib.sha256(text.encode("utf-8")).digest()


def _literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(map(repr, vector)) + "]"


async def embed_space(
    ev: AsyncConnection[Any],
    embedder: Embedder,
    space: ModelSpace,
    *,
    batch: int,
    progress: Callable[[str, int, int], None],
) -> int:
    """Embed every snapshot chunk for one model; leaves `ev` idle on return or error."""
    async with ev.transaction():
        rows = await (
            await ev.execute(
                "SELECT c.id, s.title, c.heading_path, c.content FROM chunks c"
                " JOIN sources s ON s.current_revision_id = c.revision_id ORDER BY c.id"
            )
        ).fetchall()
        cached = {
            row[0]
            for row in await (
                await ev.execute(
                    "SELECT input_sha256 FROM eval_embedding_cache WHERE model = %s",
                    (space.model,),
                )
            ).fetchall()
        }
    inputs = [
        (chunk_id, embed_input(title or "", heading_path, content))
        for chunk_id, title, heading_path, content in rows
    ]
    keys = [(chunk_id, _digest(text)) for chunk_id, text in inputs]
    todo: dict[bytes, str] = {}
    for (_, key), (_, text) in zip(keys, inputs, strict=True):
        if key not in cached:
            todo.setdefault(key, text)
    items = list(todo.items())
    for start in range(0, len(items), batch):
        chunk = items[start : start + batch]
        vectors = await embedder.embed([text for _, text in chunk], keep_alive=KEEP_ALIVE)
        async with ev.transaction(), ev.cursor() as cur:
            await cur.executemany(
                "INSERT INTO eval_embedding_cache (model, input_sha256, embedding)"
                " VALUES (%s, %s, %s::halfvec) ON CONFLICT DO NOTHING",
                [
                    (space.model, key, _literal(vec))
                    for (key, _), vec in zip(chunk, vectors, strict=True)
                ],
            )
        progress(space.model, min(start + batch, len(items)), len(items))
    async with ev.transaction():
        stale = await (
            await ev.execute(
                "SELECT id FROM embedding_spaces WHERE model = %s OR id = %s",
                (space.model, space.space_id),
            )
        ).fetchall()
        for (old_id,) in stale:
            await ev.execute("DELETE FROM chunk_embeddings WHERE space_id = %s", (old_id,))
        await ev.execute(
            "DELETE FROM embedding_spaces WHERE model = %s OR id = %s",
            (space.model, space.space_id),
        )
        await ev.execute(
            "INSERT INTO embedding_spaces (id, model, dims, is_default) VALUES (%s, %s, %s, false)",
            (space.space_id, space.model, space.dims),
        )
        await ev.execute("CREATE TEMP TABLE _chunk_keys (chunk_id uuid, key bytea) ON COMMIT DROP")
        async with (
            ev.cursor() as cur,
            cur.copy("COPY _chunk_keys (chunk_id, key) FROM STDIN") as cp,
        ):
            for chunk_id, key in keys:
                await cp.write_row((chunk_id, key))
        await ev.execute(
            "INSERT INTO chunk_embeddings (chunk_id, space_id, embedding)"
            " SELECT k.chunk_id, %s, e.embedding FROM _chunk_keys k"
            " JOIN eval_embedding_cache e ON e.model = %s AND e.input_sha256 = k.key",
            (space.space_id, space.model),
        )
    return len(items)


async def query_vectors(
    embedder: Embedder, texts: Sequence[str]
) -> tuple[list[list[float]], list[float]]:
    await embedder.embed(["warm-up"], keep_alive=KEEP_ALIVE)
    vectors: list[list[float]] = []
    timings: list[float] = []
    for text in texts:
        started = time.perf_counter()
        [vector] = await embedder.embed([text], keep_alive=KEEP_ALIVE)
        timings.append((time.perf_counter() - started) * 1000)
        vectors.append(vector)
    return vectors, timings


async def model_digests(
    client: httpx2.AsyncClient, url: str, models: Sequence[str]
) -> dict[str, str]:
    digests = dict.fromkeys(models, "unknown")
    try:
        response = await client.get(f"{url}/api/tags", timeout=5.0)
        listed = (
            {m.get("name"): m.get("digest") for m in response.json().get("models", [])}
            if response.status_code == 200
            else {}
        )
    except (httpx2.HTTPError, ValueError, AttributeError):
        return digests
    for model in models:
        digest = listed.get(model) or listed.get(f"{model}:latest")
        if isinstance(digest, str):
            digests[model] = digest
    return digests

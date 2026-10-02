"""Embed the scratch snapshot per model with a resumable cache; time query embeddings."""

import hashlib
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import httpx2
from psycopg import AsyncConnection

from ai_second_brain.config import local_model_name
from ai_second_brain.eval.database import check_ready
from ai_second_brain.knowledge.embed_text import embed_input
from ai_second_brain.knowledge.embedder import Embedder, EmbedError

KEEP_ALIVE = "30m"
SPACE_BASE = 100
ETA_AFTER_BATCHES = 3
UNKNOWN_DIGEST = "unknown"

# Query instructions from each model card, keyed by the model name without its tag.
# Documents are never prefixed; a model missing here gets its queries verbatim.
QUERY_PREFIX: dict[str, str] = {"snowflake-arctic-embed2": "query: "}


def query_prefix(model: str) -> str:
    return QUERY_PREFIX.get(model.split(":", 1)[0], "")


@dataclass(frozen=True)
class ModelSpace:
    model: str
    space_id: int
    dims: int
    digest: str = UNKNOWN_DIGEST

    @property
    def cache_model(self) -> str:
        """Cache key for this model: a re-pulled model (new digest) never reuses old vectors."""
        return self.model if self.digest == UNKNOWN_DIGEST else f"{self.model}@{self.digest}"


@dataclass(frozen=True)
class BatchProgress:
    model: str
    done: int  # chunks embedded in this run so far (cached chunks never count)
    total: int  # chunks this run has to embed
    batches: int
    seconds: float  # time spent on this run's batches


def format_eta(seconds: float) -> str:
    whole = max(0, round(seconds))
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def progress_line(p: BatchProgress) -> str:
    rate = p.done / p.seconds if p.seconds > 0 else 0.0
    eta = (
        format_eta((p.total - p.done) / rate)
        if p.batches >= ETA_AFTER_BATCHES and rate > 0
        else "…"
    )
    return f"{p.model} {p.done}/{p.total} chunks · {rate:.1f}/s · ETA {eta}"


class PreflightError(Exception):
    def __init__(self, code: str, model: str) -> None:
        super().__init__(f"{code}: {model}")
        self.code, self.model = code, model


class ModelEmbedError(Exception):
    """An embedding call failed mid-run; carries the model so the CLI can name it."""

    def __init__(self, code: str, model: str) -> None:
        super().__init__(f"{code}: {model}")
        self.code, self.model = code, model


async def preflight(
    make_embedder: Callable[[str], Embedder],
    models: Sequence[str],
    *,
    client: httpx2.AsyncClient | None = None,
    url: str | None = None,
) -> list[ModelSpace]:
    """Probe every model; with `client` and `url`, also read each model's digest."""
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
    if client is None or url is None:
        return spaces
    digests = await model_digests(client, url, models)
    return [
        ModelSpace(s.model, s.space_id, s.dims, digests.get(s.model, UNKNOWN_DIGEST))
        for s in spaces
    ]


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
    progress: Callable[[BatchProgress], None],
    clock: Callable[[], float] = time.perf_counter,
) -> int:
    """Embed every snapshot chunk for one model; leaves `ev` idle on return or error."""
    await check_ready(ev)  # only the scratch database has eval_embedding_cache
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
                    (space.cache_model,),
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
    spent = 0.0
    for number, start in enumerate(range(0, len(items), batch), start=1):
        began = clock()
        chunk = items[start : start + batch]
        vectors = await embedder.embed([text for _, text in chunk], keep_alive=KEEP_ALIVE)
        if any(len(vec) != space.dims for vec in vectors):
            raise EmbedError("embed_bad_response")
        async with ev.transaction(), ev.cursor() as cur:
            await cur.executemany(
                "INSERT INTO eval_embedding_cache (model, input_sha256, embedding)"
                " VALUES (%s, %s, %s::halfvec) ON CONFLICT DO NOTHING",
                [
                    (space.cache_model, key, _literal(vec))
                    for (key, _), vec in zip(chunk, vectors, strict=True)
                ],
            )
        spent += clock() - began
        done = min(start + batch, len(items))
        progress(BatchProgress(space.model, done, len(items), number, spent))
    async with ev.transaction():
        stale = await (
            await ev.execute(
                "SELECT id FROM embedding_spaces WHERE id >= %s AND (model = %s OR id = %s)",
                (SPACE_BASE, space.model, space.space_id),
            )
        ).fetchall()
        for (old_id,) in stale:
            await ev.execute("DELETE FROM chunk_embeddings WHERE space_id = %s", (old_id,))
        await ev.execute(
            "DELETE FROM embedding_spaces WHERE id >= %s AND (model = %s OR id = %s)",
            (SPACE_BASE, space.model, space.space_id),
        )
        # the seed space keeps its row; only its scratch-database name gives way
        await ev.execute(
            "UPDATE embedding_spaces SET model = model || '@seed' WHERE id < %s AND model = %s",
            (SPACE_BASE, space.model),
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
            (space.space_id, space.cache_model),
        )
    return len(items)


async def query_vectors(
    embedder: Embedder, texts: Sequence[str]
) -> tuple[list[list[float]], list[float]]:
    """Embed each query with its model's query prefix; the timed vectors are the ones ranked."""
    prefix = query_prefix(embedder.model)
    await embedder.embed(["warm-up"], keep_alive=KEEP_ALIVE)
    vectors: list[list[float]] = []
    timings: list[float] = []
    for text in texts:
        started = time.perf_counter()
        [vector] = await embedder.embed([prefix + text], keep_alive=KEEP_ALIVE)
        timings.append((time.perf_counter() - started) * 1000)
        vectors.append(vector)
    return vectors, timings


async def model_digests(
    client: httpx2.AsyncClient, url: str, models: Sequence[str]
) -> dict[str, str]:
    digests = dict.fromkeys(models, UNKNOWN_DIGEST)
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

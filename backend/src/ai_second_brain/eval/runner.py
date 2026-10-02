"""The bake-off pipeline (spec §6): guard, load, preflight, snapshot, embed, query, score.

Privacy: the only log line carries counts and a duration. Query text, note text, paths and
targets never reach a logger; target errors go to the owner's terminal through the CLI.
"""

import hashlib
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx2
from psycopg import AsyncConnection

from ai_second_brain.chat.providers.base import ChatTimeouts
from ai_second_brain.config import Settings
from ai_second_brain.eval.database import check_ready
from ai_second_brain.eval.embedding import (
    ModelSpace,
    embed_space,
    model_digests,
    preflight,
    query_vectors,
)
from ai_second_brain.eval.guards import check_eval_url
from ai_second_brain.eval.metrics import bootstrap_diff, first_rank, percentile, summarize
from ai_second_brain.eval.queries import EvalConfigError, EvalQuery, load_queries
from ai_second_brain.eval.snapshot import SnapshotInfo, live_paths, snapshot
from ai_second_brain.eval.verdict import ModelScore, Verdict, decide
from ai_second_brain.knowledge.embedder import Embedder
from ai_second_brain.search.query import query

log = logging.getLogger(__name__)

LIMIT = 10


@dataclass(frozen=True)
class ModelRun:
    model: str
    space_id: int
    dims: int
    digest: str
    newly_embedded: int
    hybrid: list[int | None]  # first-target ranks per query, in query order
    vector: list[int | None]
    hybrid_paths: list[list[str]]
    vector_paths: list[list[str]]
    latency_ms: list[float]


@dataclass(frozen=True)
class RunResult:
    snapshot: SnapshotInfo
    queries: list[EvalQuery]
    queries_sha256: str
    queries_path: str
    models: list[ModelRun]
    text_only: list[int | None]
    text_only_paths: list[list[str]]
    verdict: Verdict
    intervals: dict[str, tuple[float, float]]


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def _ranked(
    ev: AsyncConnection[Any],
    q: str,
    vector: list[float] | None,
    space: ModelSpace | None = None,
    *,
    text: bool = True,
) -> list[str]:
    """Distinct source paths in rank order (a note counts once)."""
    if space is None:
        result = await query(ev, q, vector=vector, limit=LIMIT, mode="search", text=text)
    else:
        result = await query(
            ev,
            q,
            vector=vector,
            limit=LIMIT,
            mode="search",
            space_id=space.space_id,
            dims=space.dims,
            text=text,
        )
    return list(dict.fromkeys(hit.path for hit in result.hits))


async def run_eval(
    settings: Settings,
    *,
    queries_path: Path,
    models: Sequence[str],
    dev_url: str,
    eval_url: str,
    test_url: str | None,
    client: httpx2.AsyncClient,
    progress: Callable[[str], None],
) -> RunResult:
    check_eval_url(eval_url, dev_url, test_url)  # before any connection or write
    started = time.perf_counter()
    queries = load_queries(queries_path)
    queries_sha256 = _file_sha256(queries_path)
    embed_url = settings.embed_url
    if embed_url is None:
        raise EvalConfigError(["no embedding host: set SB_EMBED_URL"])
    if not models:
        raise EvalConfigError(["no models to evaluate: set SB_EVAL_MODELS or pass --models"])

    def make_embedder(model: str) -> Embedder:
        return Embedder(embed_url, model, None, client, ChatTimeouts())

    spaces = await preflight(make_embedder, models)

    async with await AsyncConnection.connect(eval_url) as ev:
        await check_ready(ev)
        # dev is opened only for the snapshot (read-only inside it) and closed right after
        async with await AsyncConnection.connect(dev_url) as dev:
            info = await snapshot(dev, ev)

        live = await live_paths(ev)
        missing = [
            f"{q.id}: target not in the index: {target}"
            for q in queries
            for target in q.targets
            if target not in live
        ]
        if missing:
            raise EvalConfigError(missing)

        texts = [q.q for q in queries]
        runs: list[tuple[int, list[list[str]], list[list[str]], list[float]]] = []
        for space in spaces:
            embedder = make_embedder(space.model)

            def report(model: str, done: int, total: int) -> None:
                progress(f"{model} {done}/{total}")

            newly = await embed_space(
                ev, embedder, space, batch=settings.embed_batch, progress=report
            )
            vectors, latency = await query_vectors(embedder, texts)
            hybrid_paths: list[list[str]] = []
            vector_paths: list[list[str]] = []
            for q, vec in zip(queries, vectors, strict=True):
                hybrid_paths.append(await _ranked(ev, q.q, vec, space))
                vector_paths.append(await _ranked(ev, q.q, vec, space, text=False))
            runs.append((newly, hybrid_paths, vector_paths, latency))

        text_only_paths = [await _ranked(ev, q.q, None) for q in queries]

    digests = await model_digests(client, embed_url, [s.model for s in spaces])

    def ranks(paths: list[list[str]]) -> list[int | None]:
        return [first_rank(p, q.targets) for p, q in zip(paths, queries, strict=True)]

    model_runs = [
        ModelRun(
            model=space.model,
            space_id=space.space_id,
            dims=space.dims,
            digest=digests.get(space.model, "unknown"),
            newly_embedded=newly,
            hybrid=ranks(hybrid_paths),
            vector=ranks(vector_paths),
            hybrid_paths=hybrid_paths,
            vector_paths=vector_paths,
            latency_ms=latency,
        )
        for space, (newly, hybrid_paths, vector_paths, latency) in zip(spaces, runs, strict=True)
    ]

    def score(run: ModelRun) -> ModelScore:
        summary = summarize(run.hybrid)
        return ModelScore(run.model, summary.recall, summary.mrr, percentile(run.latency_ms, 95))

    incumbent = model_runs[0]
    verdict = decide(score(incumbent), [score(run) for run in model_runs[1:]])
    intervals = {run.model: bootstrap_diff(run.hybrid, incumbent.hybrid) for run in model_runs[1:]}
    log.info(
        "eval run models=%d queries=%d chunks=%d ms=%d",
        len(model_runs),
        len(queries),
        info.chunks,
        int((time.perf_counter() - started) * 1000),
    )
    return RunResult(
        snapshot=info,
        queries=queries,
        queries_sha256=queries_sha256,
        queries_path=str(queries_path),
        models=model_runs,
        text_only=ranks(text_only_paths),
        text_only_paths=text_only_paths,
        verdict=verdict,
        intervals=intervals,
    )

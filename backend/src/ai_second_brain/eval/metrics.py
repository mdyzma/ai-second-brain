"""Per-note retrieval metrics, a seeded paired bootstrap and flip lists. Pure functions."""

import random
from collections.abc import Sequence
from dataclasses import dataclass

from ai_second_brain.eval.queries import EvalQuery

K = 10


def first_rank(ranked: Sequence[str], targets: Sequence[str], k: int = K) -> int | None:
    wanted = set(targets)
    for rank, path in enumerate(dict.fromkeys(ranked), start=1):
        if rank > k:
            return None
        if path in wanted:
            return rank
    return None


@dataclass(frozen=True)
class Summary:
    recall: float
    mrr: float
    hit1: float
    n: int


def summarize(ranks: Sequence[int | None]) -> Summary:
    n = len(ranks)
    if n == 0:
        return Summary(0.0, 0.0, 0.0, 0)
    return Summary(
        recall=sum(r is not None for r in ranks) / n,
        mrr=sum(1 / r for r in ranks if r is not None) / n,
        hit1=sum(r == 1 for r in ranks) / n,
        n=n,
    )


def split_by(
    queries: Sequence[EvalQuery], ranks: Sequence[int | None], key: str
) -> dict[str, Summary]:
    groups: dict[str, list[int | None]] = {}
    for query, rank in zip(queries, ranks, strict=True):
        groups.setdefault(getattr(query, key), []).append(rank)
    return {name: summarize(values) for name, values in sorted(groups.items())}


def percentile(values: Sequence[float], pct: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * pct / 100
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def bootstrap_diff(
    a: Sequence[int | None], b: Sequence[int | None], *, resamples: int = 2000, seed: int = 20261002
) -> tuple[float, float]:
    hits = [(x is not None, y is not None) for x, y in zip(a, b, strict=True)]
    if not hits:
        return 0.0, 0.0
    rng = random.Random(seed)  # noqa: S311 - statistics, not security
    n = len(hits)
    diffs = []
    for _ in range(resamples):
        sample = [hits[rng.randrange(n)] for _ in range(n)]
        diffs.append(sum(x for x, _ in sample) / n - sum(y for _, y in sample) / n)
    return round(percentile(diffs, 2.5), 6), round(percentile(diffs, 97.5), 6)


def flips(
    ids: Sequence[str], a: Sequence[int | None], b: Sequence[int | None]
) -> tuple[list[tuple[str, int, int | None]], list[tuple[str, int | None, int]]]:
    gained = [(i, x, y) for i, x, y in zip(ids, a, b, strict=True) if x is not None and y is None]
    lost = [(i, x, y) for i, x, y in zip(ids, a, b, strict=True) if x is None and y is not None]
    return gained, lost  # type: ignore[return-value]

"""The pre-agreed win rule (spec §3). Applied mechanically; never tuned after a run."""

from collections.abc import Sequence
from dataclasses import dataclass

EPSILON = 1e-9


@dataclass(frozen=True)
class ModelScore:
    model: str
    recall: float
    mrr: float
    p95_ms: float


@dataclass(frozen=True)
class Check:
    model: str
    recall_ok: bool
    mrr_ok: bool
    latency_ok: bool

    @property
    def wins(self) -> bool:
        return self.recall_ok and self.mrr_ok and self.latency_ok


@dataclass(frozen=True)
class Verdict:
    winner: str | None
    checks: list[Check]
    line: str


def decide(
    incumbent: ModelScore,
    challengers: Sequence[ModelScore],
    *,
    margin: float = 0.05,
    max_p95_ms: float = 300.0,
) -> Verdict:
    checks = [
        Check(
            c.model,
            recall_ok=c.recall + EPSILON >= incumbent.recall + margin,
            mrr_ok=c.mrr + EPSILON >= incumbent.mrr,
            latency_ok=c.p95_ms < max_p95_ms,
        )
        for c in challengers
    ]
    winners = [c for c, check in zip(challengers, checks, strict=True) if check.wins]
    if not winners:
        return Verdict(None, checks, f"{incumbent.model} stays")
    best = max(winners, key=lambda c: (c.recall, c.mrr))
    return Verdict(best.model, checks, f"{best.model} wins → Phase 3b")

from uuid import UUID, uuid4

from ai_second_brain.search.evidence import select_evidence
from ai_second_brain.search.query import Hit

_ids: dict[str, UUID] = {}


def hit(source: str, size: int, score: float) -> Hit:
    return Hit(
        _ids.setdefault(source, uuid4()),
        source,
        None,
        uuid4(),
        [],
        "x" * size,
        None,
        score,
        frozenset({"text"}),
        None,
    )


def test_budget_skips_oversized_and_keeps_order() -> None:
    hits = [hit("a", 5000, 0.9), hit("b", 4000, 0.8), hit("c", 2000, 0.7), hit("d", 900, 0.6)]
    chosen = select_evidence(hits, limit=8, budget_chars=8000)
    assert [h.path for h in chosen] == ["a", "c", "d"]


def test_per_note_cap_and_limit() -> None:
    hits = [hit("a", 10, 1.0 - i / 100) for i in range(5)] + [
        hit(f"n{i}", 10, 0.5) for i in range(10)
    ]
    chosen = select_evidence(hits, limit=8)
    assert [h.path for h in chosen].count("a") == 2 and len(chosen) == 8

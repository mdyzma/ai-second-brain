"""Pick chat evidence: score order, <=2 chunks per note, <=limit chunks, ~8,000 characters."""

from collections import Counter
from collections.abc import Sequence

from ai_second_brain.search.query import Hit


def select_evidence(
    hits: Sequence[Hit], *, limit: int, budget_chars: int = 8000, per_note: int = 2
) -> list[Hit]:
    chosen: list[Hit] = []
    per_source: Counter[object] = Counter()
    used = 0
    for hit in hits:
        if len(chosen) == limit:
            break
        if per_source[hit.source_id] >= per_note or used + len(hit.content) > budget_chars:
            continue
        chosen.append(hit)
        per_source[hit.source_id] += 1
        used += len(hit.content)
    return chosen

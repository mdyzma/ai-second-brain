from typing import Literal

MatchKind = Literal["exact", "alias", "similar", "new"]


def initial_edge_status(
    *, match: MatchKind, entity_status: str, confidence: float, threshold: float
) -> Literal["accepted", "proposed"]:
    if entity_status == "accepted" and match in ("exact", "alias") and confidence >= threshold:
        return "accepted"
    return "proposed"

"""Pair deleted and added paths with the same content hash (a move), and the deletion guard."""

from collections.abc import Mapping

GUARD_MIN = 10
GUARD_RATIO = 0.2


def _shared_prefix(a: str, b: str) -> int:
    count = 0
    for x, y in zip(a.split("/")[:-1], b.split("/")[:-1], strict=False):
        if x != y:
            break
        count += 1
    return count


def pair_moves(
    deleted: Mapping[str, bytes], added: Mapping[str, bytes]
) -> tuple[list[tuple[str, str]], list[str], list[str]]:
    remaining = dict(deleted)
    pairs: list[tuple[str, str]] = []
    unpaired_added: list[str] = []
    for new in sorted(added):
        candidates = [old for old, digest in remaining.items() if digest == added[new]]
        if not candidates:
            unpaired_added.append(new)
            continue
        best = min(candidates, key=lambda old: (-_shared_prefix(old, new), old))
        pairs.append((best, new))
        del remaining[best]
    return pairs, sorted(remaining), unpaired_added


def guard_trips(to_tombstone: int, live: int) -> bool:
    return to_tombstone > GUARD_MIN and to_tombstone > GUARD_RATIO * live

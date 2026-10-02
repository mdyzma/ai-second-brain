import pytest

from ai_second_brain.eval.metrics import (
    bootstrap_diff,
    first_rank,
    flips,
    percentile,
    split_by,
    summarize,
)
from ai_second_brain.eval.queries import EvalQuery


def test_first_rank_basic_and_multiple_targets() -> None:
    assert first_rank(["a", "b", "c"], ["c"]) == 3
    assert first_rank(["a", "b", "c"], ["x", "b"]) == 2
    assert first_rank(["a"], ["x"]) is None


def test_duplicates_counted_once() -> None:
    assert first_rank(["a", "a", "a", "b"], ["b"]) == 2


def test_rank_ten_counts_rank_eleven_does_not() -> None:
    ranked = [f"n{i}" for i in range(1, 12)]
    assert first_rank(ranked, ["n10"]) == 10
    assert first_rank(ranked, ["n11"]) is None


def test_summarize() -> None:
    s = summarize([1, 2, None, 10])
    assert (s.n, s.recall, s.hit1) == (4, 0.75, 0.25)
    assert s.mrr == pytest.approx((1 + 0.5 + 0 + 0.1) / 4)
    assert summarize([]).n == 0 and summarize([]).recall == 0.0


def test_split_by_lang() -> None:
    qs = [EvalQuery("a", "x", "pl", "topic", ("t",)), EvalQuery("b", "y", "en", "topic", ("t",))]
    out = split_by(qs, [1, None], "lang")
    assert out["pl"].recall == 1.0 and out["en"].recall == 0.0


def test_bootstrap_identical_is_zero_and_seeded() -> None:
    ranks = [1, None, 3, None, 2]
    assert bootstrap_diff(ranks, ranks) == (0.0, 0.0)
    a, b = [1, 1, 1, None], [None, None, 1, None]
    assert bootstrap_diff(a, b) == bootstrap_diff(a, b)
    low, high = bootstrap_diff(a, b)
    assert low <= 0.5 <= high


def test_flips() -> None:
    gained, lost = flips(["q1", "q2", "q3"], [1, None, 4], [None, 2, 5])
    assert gained == [("q1", 1, None)] and lost == [("q2", None, 2)]


def test_percentile() -> None:
    assert percentile([10, 20, 30, 40], 50) == 25.0
    assert percentile([5.0], 95) == 5.0

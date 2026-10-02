from ai_second_brain.eval.verdict import ModelScore, decide

INC = ModelScore("bge-m3:567m", recall=0.70, mrr=0.50, p95_ms=120)


def test_incumbent_stays_when_nobody_wins() -> None:
    v = decide(INC, [ModelScore("snow", 0.74, 0.60, 100)])
    assert v.winner is None and v.line == "bge-m3:567m stays"
    c = v.checks[0]
    assert (c.recall_ok, c.mrr_ok, c.latency_ok) == (False, True, True)


def test_each_condition_fails_alone() -> None:
    assert decide(INC, [ModelScore("a", 0.76, 0.49, 100)]).winner is None  # mrr
    assert decide(INC, [ModelScore("b", 0.76, 0.55, 300)]).winner is None  # latency (not < 300)
    assert decide(INC, [ModelScore("c", 0.749, 0.55, 100)]).winner is None  # margin


def test_winner_line_and_tie_break() -> None:
    v = decide(
        INC,
        [
            ModelScore("a", 0.80, 0.55, 100),
            ModelScore("b", 0.80, 0.60, 100),
            ModelScore("c", 0.76, 0.9, 50),
        ],
    )
    assert v.winner == "b" and v.line == "b wins → Phase 3b"

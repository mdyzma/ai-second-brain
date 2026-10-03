from uuid import uuid4

from ai_second_brain.graph.decide import would_cycle


def test_cycles() -> None:
    a, b, c = uuid4(), uuid4(), uuid4()
    parents = {a: None, b: a, c: b}
    assert would_cycle(parents, a, c)  # a under c, but c is under a
    assert would_cycle(parents, a, a)
    assert not would_cycle(parents, c, a)


def test_cycles_unknown_parent_and_existing_loop() -> None:
    a, b, c, d = uuid4(), uuid4(), uuid4(), uuid4()
    assert not would_cycle({}, a, b)  # b's chain is unknown, so it just ends
    loop = {b: c, c: b}  # a loop that doesn't involve a must still terminate
    assert not would_cycle(loop, a, b)
    assert would_cycle({b: c, c: d, d: a}, a, b)

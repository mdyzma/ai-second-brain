from uuid import uuid4

from ai_second_brain.graph.schema import ExtractedEntity, ExtractedRelation, ExtractionOutput
from ai_second_brain.graph.windows import merge_outputs, split_windows


def chunks(*sizes: int) -> list[tuple]:
    return [(uuid4(), f"H{i}", "x" * size) for i, size in enumerate(sizes)]


def test_windows_respect_chunk_boundaries_and_labels() -> None:
    cs = chunks(2500, 2500, 2500)
    ws = split_windows(cs, max_chars=6000)
    assert len(ws) == 2
    assert ws[0].labels == {"c1": cs[0][0], "c2": cs[1][0]} and ws[1].labels == {"c1": cs[2][0]}
    assert all(len(w.text) <= 6000 for w in ws)
    assert "[c1]" in ws[0].text and "H0" in ws[0].text
    assert ws[1].text.startswith("[c1] H2")


def test_windows_split_long_chunk_by_chars() -> None:
    cs = chunks(100_000)
    ws = split_windows(cs, max_chars=6000)
    assert all(len(w.text) <= 6000 for w in ws)
    assert sum(w.text.count("x") for w in ws) == 100_000
    assert all(w.labels == {"c1": cs[0][0]} for w in ws)


def test_long_chunk_after_short_one_keeps_labels_valid() -> None:
    cs = chunks(100, 9000, 100)
    ws = split_windows(cs, max_chars=6000)
    assert all(len(w.text) <= 6000 for w in ws)
    assert sum(w.text.count("x") for w in ws) == 9200
    for w in ws:
        assert list(w.labels)[0] == "c1"
        for label in w.labels:
            assert f"[{label}]" in w.text


def test_empty_note_has_no_windows() -> None:
    assert split_windows([], max_chars=6000) == []


def test_merge_unions_and_keeps_best() -> None:
    a = ExtractionOutput(
        summary="first",
        entities=[ExtractedEntity(name="NAS", type="device", aliases=["nas01"], confidence=0.6)],
        relations=[
            ExtractedRelation(
                subject="NOTE", relation="about", object="NAS", chunk="c1", confidence=0.5
            )
        ],
    )
    b = ExtractionOutput(
        summary="second",
        entities=[ExtractedEntity(name="nas", type="device", aliases=["box"], confidence=0.9)],
        relations=[
            ExtractedRelation(
                subject="NOTE", relation="about", object="nas", chunk="c2", confidence=0.8
            )
        ],
    )
    m = merge_outputs([a, b])
    assert m.summary == "first"
    [e] = m.entities
    assert e.confidence == 0.9 and set(e.aliases) == {"nas01", "box"}
    [r] = m.relations
    assert r.confidence == 0.8 and r.chunk == "c1"


def test_long_heading_never_exceeds_window_and_body_is_exact() -> None:
    body = "ab " * 300
    cid = uuid4()
    ws = split_windows([(cid, "H" * 50, body)], max_chars=200)
    assert len(ws) > 1 and all(len(w.text) <= 200 for w in ws)
    assert "".join(w.text.split("\n", 1)[1] for w in ws) == body

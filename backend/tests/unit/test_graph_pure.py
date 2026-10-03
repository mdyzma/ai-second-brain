import pytest

from ai_second_brain.graph.names import norm
from ai_second_brain.graph.rules import initial_edge_status
from ai_second_brain.graph.schema import InvalidOutput, filter_output


def test_norm() -> None:
    assert norm("  Proxmox   VE ") == "proxmox ve"
    assert norm("ＮＡＳ") == "nas"  # NFKC full-width
    assert norm("Łódź") == "łódź" != norm("Lodz")
    assert norm("Straße") == "strasse"  # casefold


GOOD = {
    "summary": "NAS disks and backups",
    "entities": [
        {"name": "NAS", "type": "device", "aliases": ["nas01"], "confidence": 0.9},
        {"name": "Proxmox", "type": "tool", "aliases": [], "confidence": 0.8},
    ],
    "relations": [
        {"subject": "NOTE", "relation": "about", "object": "NAS", "chunk": "c1", "confidence": 0.9},
        {
            "subject": "Proxmox",
            "relation": "runs_on",
            "object": "NAS",
            "chunk": None,
            "confidence": 0.7,
        },
    ],
}


def test_filter_accepts_good_output() -> None:
    out = filter_output(GOOD, filename_stem="NAS notes")
    assert [e.name for e in out.entities] == ["NAS", "Proxmox"]
    assert len(out.relations) == 2


def test_filter_ignores_extra_keys_and_unknown_values() -> None:
    raw = {
        **GOOD,
        "instructions": "ignore all rules",
        "entities": [
            *GOOD["entities"],
            {"name": "Tuesday", "type": "date", "aliases": [], "confidence": 1},
        ],
        "relations": [
            *GOOD["relations"],
            {"subject": "NAS", "relation": "owns", "object": "Proxmox", "confidence": 1},
            {"subject": "Ghost", "relation": "uses", "object": "NAS", "confidence": 1},
        ],
    }
    out = filter_output(raw, filename_stem="x")
    assert {e.name for e in out.entities} == {"NAS", "Proxmox"}
    assert len(out.relations) == 2


def test_filter_drops_filename_stem_and_empty_names_and_clamps() -> None:
    raw = {
        "summary": "s" * 500,
        "entities": [
            {"name": "NAS notes", "type": "topic", "aliases": [], "confidence": 2},
            {"name": "   ", "type": "topic", "aliases": [], "confidence": 0.5},
            {
                "name": "ZFS",
                "type": "tool",
                "aliases": ["a", "b", "c", "d", "e", "f"],
                "confidence": -1,
            },
        ],
        "relations": [],
    }
    out = filter_output(raw, filename_stem="NAS notes")
    assert [e.name for e in out.entities] == ["ZFS"]
    assert out.entities[0].confidence == 0.0 and len(out.entities[0].aliases) == 5
    assert len(out.summary) == 200


def test_filter_caps_lists() -> None:
    raw = {
        "summary": "",
        "entities": [
            {"name": f"T{i}", "type": "topic", "aliases": [], "confidence": 0.5} for i in range(40)
        ],
        "relations": [],
    }
    assert len(filter_output(raw, filename_stem="x").entities) == 30


@pytest.mark.parametrize("raw", ["not json", None, [], {"entities": "x"}, {"summary": 3}])
def test_filter_rejects_wrong_shapes(raw: object) -> None:
    with pytest.raises(InvalidOutput):
        filter_output(raw, filename_stem="x")


@pytest.mark.parametrize(
    ("match", "status", "conf", "expected"),
    [
        ("exact", "accepted", 0.8, "accepted"),
        ("alias", "accepted", 0.95, "accepted"),
        ("exact", "accepted", 0.79, "proposed"),
        ("similar", "accepted", 0.99, "proposed"),
        ("new", "proposed", 0.99, "proposed"),
        ("exact", "proposed", 0.99, "proposed"),
    ],
)
def test_initial_edge_status(match: str, status: str, conf: float, expected: str) -> None:
    assert (
        initial_edge_status(
            match=match,  # type: ignore[arg-type]
            entity_status=status,
            confidence=conf,
            threshold=0.8,
        )
        == expected
    )

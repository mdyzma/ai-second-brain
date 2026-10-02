from pathlib import Path

import pytest

from ai_second_brain.eval.queries import EvalConfigError, EvalQuery, load_queries

GOOD = """
version: 1
queries:
  - id: nas-backup
    q: "kiedy są kopie zapasowe?"
    lang: pl
    kind: paraphrase
    targets: [Projects/NAS.md]
  - id: ddia
    q: leader replication
    lang: en
    kind: topic
    targets: ["Reading/Designing Data-Intensive Applications.md", Ideas/x.md]
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "queries.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_valid_file(tmp_path: Path) -> None:
    queries = load_queries(write(tmp_path, GOOD))
    assert queries[0] == EvalQuery(
        "nas-backup", "kiedy są kopie zapasowe?", "pl", "paraphrase", ("Projects/NAS.md",)
    )
    assert queries[1].targets[1] == "Ideas/x.md"


def test_all_errors_reported_together(tmp_path: Path) -> None:
    bad = """
version: 1
queries:
  - {id: a, q: "x", lang: pl, kind: topic, targets: [a.md]}
  - {id: a, q: "", lang: de, kind: topic, targets: [a.md]}
  - {id: Bad_Id, q: "y", lang: en, kind: weird, targets: []}
"""
    with pytest.raises(EvalConfigError) as info:
        load_queries(write(tmp_path, bad))
    text = "\n".join(info.value.errors)
    for needle in (
        "a: duplicate id",
        "a: q",
        "a: lang",
        "Bad_Id: id",
        "Bad_Id: kind",
        "Bad_Id: targets",
    ):
        assert needle in text


@pytest.mark.parametrize(
    "text", ["version: 2\nqueries: []\n", "not: [valid", "- just a list\n", "version: 1\n"]
)
def test_bad_file_shapes(tmp_path: Path, text: str) -> None:
    with pytest.raises(EvalConfigError):
        load_queries(write(tmp_path, text))


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(EvalConfigError) as info:
        load_queries(tmp_path / "nope.yaml")
    assert "not found" in info.value.errors[0]


def test_target_limits(tmp_path: Path) -> None:
    many = ", ".join(f"n{i}.md" for i in range(11))
    with pytest.raises(EvalConfigError):
        load_queries(
            write(
                tmp_path,
                "version: 1\nqueries:\n"
                f"  - {{id: a, q: x, lang: pl, kind: topic, targets: [{many}]}}\n",
            )
        )


def test_unreadable_or_non_utf8_file_is_config_error(tmp_path: Path) -> None:
    path = tmp_path / "queries.yaml"
    path.write_bytes(b"version: 1\nqueries: [\xff\xfe]\n")
    with pytest.raises(EvalConfigError):
        load_queries(path)

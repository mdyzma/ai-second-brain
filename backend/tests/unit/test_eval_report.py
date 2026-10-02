import json
from datetime import UTC, datetime
from pathlib import Path

from ai_second_brain.eval.queries import EvalQuery
from ai_second_brain.eval.report import render_markdown, write_report
from ai_second_brain.eval.runner import ModelRun, RunResult
from ai_second_brain.eval.snapshot import SnapshotInfo
from ai_second_brain.eval.verdict import Check, Verdict

QUERIES = [
    EvalQuery(
        "nas-backup", "o której idą kopie zapasowe", "pl", "paraphrase", ("Projects/NAS.md",)
    ),
    EvalQuery("raid-level", "RAID 5 secret phrase", "en", "identifier", ("Projects/NAS.md",)),
    EvalQuery("proxmox", "klaster wirtualizacji domowej", "pl", "topic", ("Projects/Proxmox.md",)),
]


def _run(model: str, hybrid: list[int | None], digest: str, latency: list[float]) -> ModelRun:
    paths = [["Projects/NAS.md"] if r == 1 else ["Filler/f0.md"] for r in hybrid]
    return ModelRun(
        model=model,
        space_id=100,
        dims=1024,
        digest=digest,
        newly_embedded=7,
        hybrid=hybrid,
        vector=hybrid,
        hybrid_paths=paths,
        vector_paths=paths,
        latency_ms=latency,
    )


def _result() -> RunResult:
    return RunResult(
        snapshot=SnapshotInfo(14, 31, datetime(2026, 10, 2, 11, 59, tzinfo=UTC)),
        queries=QUERIES,
        queries_sha256="ab" * 32,
        queries_path="C:/owner/eval/queries.yaml",
        models=[
            _run("bge-m3", [None, 1, None], "sha256:incumbentdigest", [10.0, 20.0, 30.0]),
            _run("good-model", [1, 1, 2], "sha256:challengerdigest", [40.0, 50.0, 400.0]),
        ],
        text_only=[None, 1, None],
        text_only_paths=[[], ["Projects/NAS.md"], []],
        verdict=Verdict(
            "good-model",
            [Check("good-model", recall_ok=True, mrr_ok=True, latency_ok=False)],
            "good-model wins → Phase 3b",
        ),
        intervals={"good-model": (0.333333, 1.0)},
    )


def test_markdown_has_every_section() -> None:
    md = render_markdown(_result())
    assert "good-model wins → Phase 3b" in md
    assert "| bge-m3 | hybrid | 33.3% | 0.333 | 33.3% | 3 |" in md
    assert "| good-model | hybrid | 100.0% | 0.833 | 66.7% | 3 |" in md
    assert "| good-model | vector | 100.0% |" in md
    assert "| (none) | text-only | 33.3% |" in md
    assert "| bge-m3 | 20.0 | 29.0 |" in md  # latency p50, p95
    assert "| good-model | ✓ | ✓ | ✗ | ✗ | [+33.3 pp, +100.0 pp] |" in md
    assert "| good-model | en | 100.0% |" in md and "| bge-m3 | pl | 0.0% |" in md
    assert "| good-model | paraphrase |" in md and "| bge-m3 | identifier | 100.0% |" in md
    assert "| good-model | gained | nas-backup | 1 | – |" in md
    assert "| good-model | gained | proxmox | 2 | – |" in md
    assert "14 notes, 31 chunks" in md
    assert "sha256:incumbentdigest" in md and "sha256:challengerdigest" in md
    assert "ab" * 32 in md
    order = [
        md.index("good-model wins"),
        md.index("## Summary"),
        md.index("latency"),
        md.index("## Win rule"),
        md.index("by lang"),
        md.index("by kind"),
        md.index("## Flips"),
        md.index("## Snapshot"),
        md.index("## Query set"),
    ]
    assert order == sorted(order)


def test_markdown_has_no_query_text() -> None:
    md = render_markdown(_result())
    for query in QUERIES:
        assert query.q not in md


def test_write_report_folder_and_json(tmp_path: Path) -> None:
    now = datetime(2026, 10, 2, 12, 0, 0)
    folder = write_report(_result(), tmp_path / "reports", now)
    assert folder.name == "20261002-120000"
    second = write_report(_result(), tmp_path / "reports", now)
    assert second.name == "20261002-120000-2"
    data = json.loads((folder / "results.json").read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert data["snapshot"]["sources"] == 14
    assert [m["digest"] for m in data["models"]] == [
        "sha256:incumbentdigest",
        "sha256:challengerdigest",
    ]
    first = data["queries"][0]
    assert first["id"] == "nas-backup"
    assert first["targets"] == ["Projects/NAS.md"]
    assert first["runs"]["good-model"]["hybrid"] == ["Projects/NAS.md"]
    assert first["runs"]["bge-m3"]["latency_ms"] == 10.0
    assert data["queries"][1]["text_only"] == ["Projects/NAS.md"]
    raw = (folder / "results.json").read_text(encoding="utf-8")
    assert "→" in raw  # ensure_ascii=False keeps the verdict readable

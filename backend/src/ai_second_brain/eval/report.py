"""Render a bake-off result as `report.md` + `results.json` (spec §7.4).

The markdown names queries by id only, never by text. `results.json` holds the ranked paths
so a run can be inspected later; both files live outside the repository (SB_EVAL_DIR).
"""

import json
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from ai_second_brain.eval.metrics import Summary, flips, percentile, split_by, summarize
from ai_second_brain.eval.runner import RunResult

TICK, CROSS = "✓", "✗"


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _pp(x: float) -> str:
    return f"{x * 100:+.1f} pp"


def _rank(rank: int | None) -> str:
    return "–" if rank is None else str(rank)


def _mark(ok: bool) -> str:
    return TICK if ok else CROSS


def _table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return lines


def _summary_row(model: str, run: str, s: Summary) -> list[str]:
    return [model, run, _pct(s.recall), f"{s.mrr:.3f}", _pct(s.hit1), str(s.n)]


def summary_rows(result: RunResult) -> list[list[str]]:
    rows = []
    for run in result.models:
        rows.append(_summary_row(run.model, "hybrid", summarize(run.hybrid)))
        rows.append(_summary_row(run.model, "vector", summarize(run.vector)))
    rows.append(_summary_row("(none)", "text-only", summarize(result.text_only)))
    return rows


SUMMARY_HEADER = ["model", "run", "recall@10", "MRR@10", "hit@1", "n"]


def render_markdown(result: RunResult) -> str:
    incumbent = result.models[0]
    ids = [q.id for q in result.queries]
    out: list[str] = ["# Embedding bake-off", "", f"**Verdict: {result.verdict.line}**", ""]

    out += ["## Summary", ""]
    out += _table(SUMMARY_HEADER, summary_rows(result))

    out += ["", "## Query-embedding latency", ""]
    out += _table(
        ["model", "p50 ms", "p95 ms"],
        [
            [
                run.model,
                f"{percentile(run.latency_ms, 50):.1f}",
                f"{percentile(run.latency_ms, 95):.1f}",
            ]
            for run in result.models
        ],
    )

    out += ["", f"## Win rule (challengers against {incumbent.model})", ""]
    out += [
        "A challenger wins only if hybrid recall@10 ≥ incumbent + 5 pp, hybrid MRR@10 ≥"
        " incumbent, and query-embedding p95 < 300 ms.",
        "",
    ]
    rows = []
    for check in result.verdict.checks:
        low, high = result.intervals.get(check.model, (0.0, 0.0))
        rows.append(
            [
                check.model,
                _mark(check.recall_ok),
                _mark(check.mrr_ok),
                _mark(check.latency_ok),
                _mark(check.wins),
                f"[{_pp(low)}, {_pp(high)}]",
            ]
        )
    out += _table(
        ["challenger", "recall +5 pp", "MRR ≥", "p95 < 300 ms", "wins", "recall diff 95% CI"],
        rows or [["(no challengers)", "", "", "", "", ""]],
    )

    for key in ("lang", "kind"):
        out += ["", f"## Hybrid by {key}", ""]
        split_rows = []
        for run in result.models:
            for name, s in split_by(result.queries, run.hybrid, key).items():
                split_rows.append(
                    [run.model, name, _pct(s.recall), f"{s.mrr:.3f}", _pct(s.hit1), str(s.n)]
                )
        out += _table(["model", key, "recall@10", "MRR@10", "hit@1", "n"], split_rows)

    out += ["", "## Flips (hybrid, against the incumbent)", ""]
    flip_rows = []
    for run in result.models[1:]:
        gained, lost = flips(ids, run.hybrid, incumbent.hybrid)
        flip_rows += [[run.model, "gained", qid, _rank(a), _rank(b)] for qid, a, b in gained]
        flip_rows += [[run.model, "lost", qid, _rank(a), _rank(b)] for qid, a, b in lost]
    out += _table(
        ["challenger", "flip", "query id", "challenger rank", "incumbent rank"],
        flip_rows or [["(none)", "", "", "", ""]],
    )

    snap = result.snapshot
    out += ["", "## Snapshot and models", ""]
    out += [
        f"- Snapshot taken at {snap.taken_at.isoformat(timespec='seconds')}:"
        f" {snap.sources} notes, {snap.chunks} chunks.",
        "",
    ]
    out += _table(
        ["model", "space", "dims", "digest", "newly embedded"],
        [
            [run.model, str(run.space_id), str(run.dims), run.digest, str(run.newly_embedded)]
            for run in result.models
        ],
    )

    out += ["", "## Query set", ""]
    out += [
        f"- File: `{result.queries_path}`",
        f"- SHA-256: `{result.queries_sha256}`",
        f"- Queries: {len(result.queries)}",
        "",
    ]
    return "\n".join(out)


def results_json(result: RunResult) -> dict[str, Any]:
    snap = result.snapshot
    return {
        "version": 1,
        "verdict": {"line": result.verdict.line, "winner": result.verdict.winner},
        "queries_file": {"path": result.queries_path, "sha256": result.queries_sha256},
        "snapshot": {
            "sources": snap.sources,
            "chunks": snap.chunks,
            "taken_at": snap.taken_at.isoformat(),
        },
        "models": [
            {
                "model": run.model,
                "space_id": run.space_id,
                "dims": run.dims,
                "digest": run.digest,
                "newly_embedded": run.newly_embedded,
                "hybrid": asdict(summarize(run.hybrid)),
                "vector": asdict(summarize(run.vector)),
                "p50_ms": percentile(run.latency_ms, 50),
                "p95_ms": percentile(run.latency_ms, 95),
                "recall_diff_ci95": list(result.intervals[run.model])
                if run.model in result.intervals
                else None,
            }
            for run in result.models
        ],
        "queries": [
            {
                "id": q.id,
                "lang": q.lang,
                "kind": q.kind,
                "targets": list(q.targets),
                "runs": {
                    run.model: {
                        "hybrid": run.hybrid_paths[i],
                        "vector": run.vector_paths[i],
                        "latency_ms": run.latency_ms[i],
                    }
                    for run in result.models
                },
                "text_only": result.text_only_paths[i],
            }
            for i, q in enumerate(result.queries)
        ],
    }


def write_report(result: RunResult, out_dir: Path, now: datetime) -> Path:
    """Write one run folder `<YYYYMMDD-HHMMSS>[-N]` under `out_dir`; return it."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%d-%H%M%S")
    folder = out_dir / stamp
    suffix = 1
    while True:
        try:
            folder.mkdir(exist_ok=False)
            break
        except FileExistsError:
            suffix += 1
            folder = out_dir / f"{stamp}-{suffix}"
    (folder / "report.md").write_text(render_markdown(result), encoding="utf-8")
    (folder / "results.json").write_text(
        json.dumps(results_json(result), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return folder

# Phase 3: Embedding Evaluation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A CLI harness that embeds a snapshot of the owner's vault with several local models in a scratch database. It runs an owner-written query set through the production search query, then writes a report with a pre-agreed verdict on whether bge-m3 stays.

**Architecture:**
- The new `ai_second_brain.eval` package holds pure pieces (query loader, metrics, bootstrap, verdict, report) and database pieces (scratch-DB prepare and guards, snapshot, an embedding cache, the runner).
- `search.query()` gains `space_id`, `dims` and `text` parameters, so the harness ranks exactly as the Search page does.
- `ai-second-brain eval prepare|suggest|check|run` and `just eval-*` recipes drive it.

**Tech Stack:** Python 3.12, psycopg 3 (async, COPY), pgvector halfvec, PyYAML, Typer, dbmate (via subprocess), and the existing Ollama `Embedder`.

**Spec:** `docs/superpowers/specs/2026-10-02-phase-3-embedding-evaluation-design.md`. Read it with this plan; the spec wins on conflicts.

## Global Constraints

- **Default candidates:** `bge-m3,snowflake-arctic-embed2,granite-embedding:278m,paraphrase-multilingual`. The first is the incumbent. If `SB_EMBED_MODEL` is a tag of it (`model_matches_space`), it is replaced by that exact tag. Every tag must pass `config.local_model_name`.
- **Win rule:** a challenger wins only if all three hold:
  - hybrid recall@10 ≥ the incumbent's + 0.05;
  - hybrid MRR@10 ≥ the incumbent's;
  - query-embedding p95 < 300 ms.

  With several winners, the highest recall@10 wins, then the highest MRR@10. The verdict line is `<incumbent tag> stays` or `<model> wins → Phase 3b`.
- **Settings:**
  - `SB_EVAL_QUERIES` defaults to `~/.second-brain/eval/queries.yaml`.
  - `SB_EVAL_DIR` defaults to `~/.second-brain/eval/reports` and is refused if it resolves under `REPO_ROOT`.
  - `SB_EVAL_DATABASE_URL` defaults to `DATABASE_URL` with the database name suffixed `_eval`. It must differ from both `DATABASE_URL` and `TEST_DATABASE_URL`, after normalising host (`localhost` is treated as `127.0.0.1`), port (default 5432) and database name.
  - `SB_EVAL_MODELS` is comma-separated.
- **Query file:** `version: 1`, with each query's fields constrained as follows:
  - `id` matches `^[a-z0-9-]{1,64}$` and is unique;
  - `q` is 1–500 characters after trimming;
  - `lang` is `pl` or `en`;
  - `kind` is `identifier`, `paraphrase` or `topic`;
  - `targets` holds 1–10 vault-relative paths.
- **Scratch spaces:** they use `embedding_spaces` ids `100 + i` (in model order). The scratch database has no HNSW index for them, so vector ranking is exact.
- **Embedding:**
  - The input is `knowledge.embed_text.embed_input(title, heading_path, content)`.
  - The cache key is `sha256(input)`.
  - Batches are `SB_EMBED_BATCH`, each sent with `keep_alive="30m"`, and the cache is upserted per batch.
- **Ranking:** queries use `limit=10` and `mode="search"`. The ranked lists are distinct source **paths**, in order.
- **Metrics:** recall@10, MRR@10 and hit@1, computed per note. They are split by `lang` and `kind`. The paired bootstrap uses 2,000 resamples and `random.Random(20261002)`, and reports a 95% percentile interval.
- **Report:**
  - The output directory is `SB_EVAL_DIR/<YYYYMMDD-HHMMSS>/`, holding `report.md` and `results.json` (`version: 1`).
  - Exit codes: 0 when the run completes (whatever the verdict), 1 on a config or preflight error, 2 on a runtime failure.
- **Privacy:**
  - Logs carry counts, model tags, durations and error codes only, never query text, note text, paths or targets.
  - The dev DB is read inside `SET TRANSACTION READ ONLY` and never written to.
- **Ruling (plan):** spec §6.1 names a `db::eval-prepare` recipe. Because the eval URL is derived in Python, preparation is instead `ai-second-brain eval prepare`, which runs dbmate through `subprocess`. The root recipe `just eval-prepare` wraps it, and `just eval-run` depends on it. The two dbmate runs and the separate `schema_migrations_eval` table are as the spec describes. Cost if wrong: one recipe moves.
- **Commits:** Conventional Commits on `main`. Never add `Co-Authored-By` or AI attribution, and never push; the owner pushes once at the end.
- **Running tests:** use `just backend::test …`, which sets `TEST_DATABASE_URL`. Run commands in the foreground with timeouts. Never kill Docker.

## Review Focus

1. **A query file with mistakes everywhere** (a duplicate id, an empty `q`, a missing target, a wrong `lang`). Every error is reported at once with its query id, never just the first. Pinned in Task 1 (`test_all_errors_reported_together`).
2. **Pointing the eval database at the dev database**, for example by setting `SB_EVAL_DATABASE_URL` to the dev URL spelled with `localhost` instead of `127.0.0.1`. The run is refused before any write. Pinned in Task 1 (`test_eval_url_equal_to_dev_after_normalising_is_refused`) and Task 4 (`test_run_refuses_dev_url`).
3. **A run interrupted halfway through embedding**, for example by Ctrl+C or Ollama crashing. Rerunning resumes from the cache and only embeds what's missing. Pinned in Task 5 (`test_interrupted_embedding_resumes`).
4. **Ties and duplicates in ranked lists**, such as the same note appearing twice or a target at rank 10 versus rank 11. The metrics count notes once and respect the cut-off exactly. Pinned in Task 2 (`test_duplicates_counted_once`, `test_rank_ten_counts_rank_eleven_does_not`).
5. **A model that is not pulled**, or a `:cloud` tag in `SB_EVAL_MODELS`. The run fails fast with `ollama pull <tag>`, or is refused, before snapshotting. Pinned in Task 5 (`test_preflight_missing_model`) and Task 1 (`test_cloud_model_refused`).

---

## File structure

| File | Responsibility |
|---|---|
| `backend/src/ai_second_brain/config.py` (modify) | eval settings and properties |
| `backend/src/ai_second_brain/eval/__init__.py` | package docstring |
| `eval/queries.py` | `EvalQuery`, `EvalConfigError`, `load_queries` |
| `eval/guards.py` | `same_database`, `check_eval_url` |
| `eval/metrics.py` | per-query scores, `Summary`, `summarize`, `split_by`, `bootstrap_diff`, `flips`, `percentile` |
| `eval/verdict.py` | `ModelScore`, `Verdict`, `decide` |
| `eval/database.py` | `dbmate_base`, `prepare`, `check_ready` |
| `eval/snapshot.py` | `SnapshotInfo`, `snapshot`, `live_paths` |
| `eval/embedding.py` | `preflight`, `embed_space`, `query_vectors`, `model_digests` |
| `eval/runner.py` | `ModelRun`, `RunResult`, `run_eval` |
| `eval/report.py` | `render_markdown`, `write_report` |
| `search/query.py` (modify) | `space_id`, `dims`, `text` params |
| `knowledge/embedder.py` (modify) | `dims: int \| None` (None = any consistent length) |
| `interfaces/cli/main.py` (modify) | `eval` sub-app: `prepare`, `suggest`, `check`, `run` |
| `db/eval/migrations/20261002100000_eval_cache.sql` | scratch-only cache table |
| root `justfile` (modify) | `eval-prepare`, `eval-suggest`, `eval-check`, `eval-run` |
| `backend/tests/fakes/ollama.py` (modify) | per-model topic maps; missing models |
| `backend/tests/eval_db.py` | test fixture that creates `<test db>_eval` from `db/schema.sql` + the eval migration |
| `backend/tests/fixtures/eval/queries.yaml` | synthetic query set for the integration run |

---

### Task 1: Settings, guards and the query loader

**Files:**
- Modify: `backend/src/ai_second_brain/config.py`
- Create: `backend/src/ai_second_brain/eval/__init__.py`, `eval/queries.py`, `eval/guards.py`
- Test: `backend/tests/unit/test_eval_config.py`, `backend/tests/unit/test_eval_queries.py`

**Interfaces:**
- Produces:
  - Settings fields `eval_queries: Path`, `eval_dir: Path`, `eval_database_url_override: str` (alias `SB_EVAL_DATABASE_URL`) and `eval_models: str`.
  - Properties `eval_queries_path -> Path`, `eval_report_dir -> Path`, `eval_database_url -> str` and `eval_model_list -> list[str]`.
  - `same_database(a: str, b: str) -> bool` and `check_eval_url(eval_url: str, dev_url: str, test_url: str | None) -> None`. The latter raises `EvalConfigError`.
  - `EvalQuery(id, q, lang, kind, targets: tuple[str, ...])`, `EvalConfigError(errors: list[str])` and `load_queries(path: Path) -> list[EvalQuery]`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/unit/test_eval_config.py`:

```python
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from ai_second_brain.config import REPO_ROOT, Settings
from ai_second_brain.eval.guards import check_eval_url, same_database
from ai_second_brain.eval.queries import EvalConfigError

from ..conftest import TEST_HASH

DEV = "postgres://brain:brain@127.0.0.1:5433/ai_second_brain?sslmode=disable"
TEST = "postgres://brain:brain@127.0.0.1:5433/ai_second_brain_test?sslmode=disable"


def make(**values: Any) -> Settings:
    base: dict[str, Any] = {"DATABASE_URL": DEV, "owner_password_hash": TEST_HASH}
    return Settings(_env_file=None, **(base | values))  # pyright: ignore[reportCallIssue]


def test_eval_url_default_suffixes_database_name() -> None:
    assert make().eval_database_url == (
        "postgres://brain:brain@127.0.0.1:5433/ai_second_brain_eval?sslmode=disable"
    )


def test_eval_url_override() -> None:
    url = "postgres://u:p@h:5432/other"
    assert make(SB_EVAL_DATABASE_URL=url).eval_database_url == url


def test_eval_model_list_replaces_incumbent_with_embed_tag() -> None:
    assert make(embed_model="bge-m3:567m").eval_model_list == [
        "bge-m3:567m", "snowflake-arctic-embed2", "granite-embedding:278m", "paraphrase-multilingual",
    ]


def test_cloud_model_refused() -> None:
    with pytest.raises(ValidationError):
        make(eval_models="bge-m3,gpt-oss:120b-cloud")


def test_eval_dir_inside_repo_refused() -> None:
    with pytest.raises(ValidationError):
        make(eval_dir=str(REPO_ROOT / "reports"))


def test_paths_expand_user() -> None:
    settings = make()
    assert settings.eval_queries_path == Path("~/.second-brain/eval/queries.yaml").expanduser()
    assert settings.eval_report_dir == Path("~/.second-brain/eval/reports").expanduser()


def test_same_database_normalises() -> None:
    assert same_database(DEV, "postgres://x:y@localhost:5433/ai_second_brain")
    assert same_database("postgres://a@h/db", "postgres://a@h:5432/db")
    assert not same_database(DEV, TEST)


def test_eval_url_equal_to_dev_after_normalising_is_refused() -> None:
    with pytest.raises(EvalConfigError):
        check_eval_url("postgres://brain:brain@localhost:5433/ai_second_brain", DEV, TEST)
    with pytest.raises(EvalConfigError):
        check_eval_url(TEST, DEV, TEST)
    check_eval_url(make().eval_database_url, DEV, TEST)  # no raise
```

`backend/tests/unit/test_eval_queries.py`:

```python
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
    assert queries[0] == EvalQuery("nas-backup", "kiedy są kopie zapasowe?", "pl", "paraphrase", ("Projects/NAS.md",))
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
    for needle in ("a: duplicate id", "a: q", "a: lang", "Bad_Id: id", "Bad_Id: kind", "Bad_Id: targets"):
        assert needle in text


@pytest.mark.parametrize("text", ["version: 2\nqueries: []\n", "not: [valid", "- just a list\n", "version: 1\n"])
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
        load_queries(write(tmp_path, f"version: 1\nqueries:\n  - {{id: a, q: x, lang: pl, kind: topic, targets: [{many}]}}\n"))
```

If `TEST_HASH` lives elsewhere, import it the way `tests/unit/test_settings_2b.py` does.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd backend; uv run pytest tests/unit/test_eval_config.py tests/unit/test_eval_queries.py -q`
Expected: FAIL with `ModuleNotFoundError: ai_second_brain.eval`.

- [ ] **Step 3: Implement**

`eval/__init__.py`:

```python
"""Embedding bake-off: owner-written queries, scratch DB, production search, fixed win rule."""
```

`eval/queries.py`:

```python
"""Load and validate the owner's query set. Errors name query ids, never query text."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

ID = re.compile(r"^[a-z0-9-]{1,64}$")
LANGS = ("pl", "en")
KINDS = ("identifier", "paraphrase", "topic")
Lang = Literal["pl", "en"]
Kind = Literal["identifier", "paraphrase", "topic"]


class EvalConfigError(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__(f"{len(errors)} problem(s) in the evaluation setup")
        self.errors = errors


@dataclass(frozen=True)
class EvalQuery:
    id: str
    q: str
    lang: str
    kind: str
    targets: tuple[str, ...]


def load_queries(path: Path) -> list[EvalQuery]:
    if not path.is_file():
        raise EvalConfigError([f"queries file not found: {path}"])
    try:
        data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        raise EvalConfigError(["queries file is not valid YAML"]) from None
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("queries"), list):
        raise EvalConfigError(["queries file must be a mapping with version: 1 and a queries list"])
    errors: list[str] = []
    seen: set[str] = set()
    out: list[EvalQuery] = []
    for index, item in enumerate(data["queries"]):
        if not isinstance(item, dict):
            errors.append(f"#{index}: entry must be a mapping")
            continue
        qid = str(item.get("id", f"#{index}"))
        if not ID.match(qid):
            errors.append(f"{qid}: id must match [a-z0-9-]{{1,64}}")
        if qid in seen:
            errors.append(f"{qid}: duplicate id")
        seen.add(qid)
        q = item.get("q")
        if not isinstance(q, str) or not q.strip() or len(q.strip()) > 500:
            errors.append(f"{qid}: q must be 1-500 characters (write a question)")
        if item.get("lang") not in LANGS:
            errors.append(f"{qid}: lang must be pl or en")
        if item.get("kind") not in KINDS:
            errors.append(f"{qid}: kind must be identifier, paraphrase or topic")
        targets = item.get("targets")
        if (
            not isinstance(targets, list)
            or not 1 <= len(targets) <= 10
            or not all(isinstance(t, str) and t.strip() for t in targets)
        ):
            errors.append(f"{qid}: targets must be 1-10 vault paths")
            targets = []
        out.append(EvalQuery(qid, str(q or "").strip(), str(item.get("lang")), str(item.get("kind")),
                             tuple(t.strip() for t in targets)))
    if errors:
        raise EvalConfigError(errors)
    return out
```

`eval/guards.py`:

```python
"""Never let the scratch database be the dev or test database."""

from urllib.parse import urlsplit

from ai_second_brain.eval.queries import EvalConfigError


def _key(url: str) -> tuple[str, int, str]:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    host = "127.0.0.1" if host in ("localhost", "::1") else host
    return host, parts.port or 5432, parts.path.lstrip("/")


def same_database(a: str, b: str) -> bool:
    return _key(a) == _key(b)


def check_eval_url(eval_url: str, dev_url: str, test_url: str | None) -> None:
    if same_database(eval_url, dev_url) or (test_url and same_database(eval_url, test_url)):
        raise EvalConfigError(["SB_EVAL_DATABASE_URL must not be the dev or test database"])
```

In `config.py`, add these fields after `retrieval_min_similarity`:

```python
    eval_queries: Path = Path("~/.second-brain/eval/queries.yaml")
    eval_dir: Path = Path("~/.second-brain/eval/reports")
    eval_database_url_override: str = Field(default="", validation_alias="SB_EVAL_DATABASE_URL")
    eval_models: str = "bge-m3,snowflake-arctic-embed2,granite-embedding:278m,paraphrase-multilingual"
```

Add the validators and properties:

```python
    @field_validator("eval_models")
    @classmethod
    def _eval_models_local(cls, value: str) -> str:
        tags = [t.strip() for t in value.split(",") if t.strip()]
        if not tags:
            raise ValueError("SB_EVAL_MODELS needs at least one model")
        for tag in tags:
            local_model_name(tag)
        return ",".join(tags)

    @field_validator("eval_dir")
    @classmethod
    def _eval_dir_outside_repo(cls, value: Path) -> Path:
        resolved = value.expanduser().resolve()
        if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
            raise ValueError("SB_EVAL_DIR must be outside the repository (reports name your notes)")
        return value

    @property
    def eval_queries_path(self) -> Path:
        return self.eval_queries.expanduser()

    @property
    def eval_report_dir(self) -> Path:
        return self.eval_dir.expanduser()

    @property
    def eval_database_url(self) -> str:
        if self.eval_database_url_override.strip():
            return self.eval_database_url_override.strip()
        parts = urlsplit(self.database_url)
        return urlunsplit(parts._replace(path=f"{parts.path.rstrip('/')}_eval"))

    @property
    def eval_model_list(self) -> list[str]:
        tags = self.eval_models.split(",")
        if model_matches_space(self.embed_model, tags[0]):
            tags[0] = self.embed_model
        return tags
```

Import `urlunsplit` next to `urlsplit`.

`model_matches_space("bge-m3:567m", "bge-m3")` is True, so the incumbent becomes `bge-m3:567m`.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `cd backend; uv run pytest tests/unit/test_eval_config.py tests/unit/test_eval_queries.py -q`, then `cd ..; just backend::check`.
Expected: PASS, and the checks are clean.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ai_second_brain/config.py backend/src/ai_second_brain/eval backend/tests/unit/test_eval_config.py backend/tests/unit/test_eval_queries.py
git commit -m "feat(eval): add eval settings, URL guards and query loader"
```

---

### Task 2: Metrics, bootstrap and verdict

**Files:**
- Create: `backend/src/ai_second_brain/eval/metrics.py`, `eval/verdict.py`
- Test: `backend/tests/unit/test_eval_metrics.py`, `backend/tests/unit/test_eval_verdict.py`

**Interfaces:**
- Consumes: `EvalQuery` from Task 1.
- Produces:

```python
# metrics.py
K = 10
def first_rank(ranked: Sequence[str], targets: Sequence[str], k: int = K) -> int | None  # 1-based, per note
@dataclass(frozen=True)
class Summary: recall: float; mrr: float; hit1: float; n: int
def summarize(ranks: Sequence[int | None]) -> Summary
def split_by(queries: Sequence[EvalQuery], ranks: Sequence[int | None], key: str) -> dict[str, Summary]
def bootstrap_diff(a: Sequence[int | None], b: Sequence[int | None], *, resamples: int = 2000,
                   seed: int = 20261002) -> tuple[float, float]   # 95% CI of recall(a) - recall(b)
def flips(ids: Sequence[str], a: Sequence[int | None], b: Sequence[int | None]) -> tuple[list[tuple[str, int, int | None]], list[tuple[str, int | None, int]]]
def percentile(values: Sequence[float], pct: float) -> float
# verdict.py
@dataclass(frozen=True)
class ModelScore: model: str; recall: float; mrr: float; p95_ms: float
@dataclass(frozen=True)
class Check: model: str; recall_ok: bool; mrr_ok: bool; latency_ok: bool
@dataclass(frozen=True)
class Verdict: winner: str | None; checks: list[Check]; line: str
def decide(incumbent: ModelScore, challengers: Sequence[ModelScore], *, margin: float = 0.05, max_p95_ms: float = 300.0) -> Verdict
```

- [ ] **Step 1: Write the failing tests**

`backend/tests/unit/test_eval_metrics.py`:

```python
import pytest

from ai_second_brain.eval.metrics import (
    bootstrap_diff, first_rank, flips, percentile, split_by, summarize,
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
```

`backend/tests/unit/test_eval_verdict.py`:

```python
from ai_second_brain.eval.verdict import ModelScore, decide

INC = ModelScore("bge-m3:567m", recall=0.70, mrr=0.50, p95_ms=120)


def test_incumbent_stays_when_nobody_wins() -> None:
    v = decide(INC, [ModelScore("snow", 0.74, 0.60, 100)])
    assert v.winner is None and v.line == "bge-m3:567m stays"
    assert (v.checks[0].recall_ok, v.checks[0].mrr_ok, v.checks[0].latency_ok) == (False, True, True)


def test_each_condition_fails_alone() -> None:
    assert decide(INC, [ModelScore("a", 0.76, 0.49, 100)]).winner is None   # mrr
    assert decide(INC, [ModelScore("b", 0.76, 0.55, 300)]).winner is None   # latency (not < 300)
    assert decide(INC, [ModelScore("c", 0.749, 0.55, 100)]).winner is None  # margin


def test_winner_line_and_tie_break() -> None:
    v = decide(INC, [ModelScore("a", 0.80, 0.55, 100), ModelScore("b", 0.80, 0.60, 100), ModelScore("c", 0.76, 0.9, 50)])
    assert v.winner == "b" and v.line == "b wins → Phase 3b"
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `cd backend; uv run pytest tests/unit/test_eval_metrics.py tests/unit/test_eval_verdict.py -q`
Expected: FAIL with an import error.

- [ ] **Step 3: Implement**

`eval/metrics.py`:

```python
"""Per-note retrieval metrics, a seeded paired bootstrap and flip lists. Pure functions."""

import random
from collections.abc import Sequence
from dataclasses import dataclass

from ai_second_brain.eval.queries import EvalQuery

K = 10


def first_rank(ranked: Sequence[str], targets: Sequence[str], k: int = K) -> int | None:
    wanted = set(targets)
    for rank, path in enumerate(dict.fromkeys(ranked), start=1):
        if rank > k:
            return None
        if path in wanted:
            return rank
    return None


@dataclass(frozen=True)
class Summary:
    recall: float
    mrr: float
    hit1: float
    n: int


def summarize(ranks: Sequence[int | None]) -> Summary:
    n = len(ranks)
    if n == 0:
        return Summary(0.0, 0.0, 0.0, 0)
    return Summary(
        recall=sum(r is not None for r in ranks) / n,
        mrr=sum(1 / r for r in ranks if r is not None) / n,
        hit1=sum(r == 1 for r in ranks) / n,
        n=n,
    )


def split_by(queries: Sequence[EvalQuery], ranks: Sequence[int | None], key: str) -> dict[str, Summary]:
    groups: dict[str, list[int | None]] = {}
    for query, rank in zip(queries, ranks, strict=True):
        groups.setdefault(getattr(query, key), []).append(rank)
    return {name: summarize(values) for name, values in sorted(groups.items())}


def percentile(values: Sequence[float], pct: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * pct / 100
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def bootstrap_diff(
    a: Sequence[int | None], b: Sequence[int | None], *, resamples: int = 2000, seed: int = 20261002
) -> tuple[float, float]:
    hits = [(x is not None, y is not None) for x, y in zip(a, b, strict=True)]
    if not hits:
        return 0.0, 0.0
    rng = random.Random(seed)  # noqa: S311 - statistics, not security
    n = len(hits)
    diffs = []
    for _ in range(resamples):
        sample = [hits[rng.randrange(n)] for _ in range(n)]
        diffs.append(sum(x for x, _ in sample) / n - sum(y for _, y in sample) / n)
    return round(percentile(diffs, 2.5), 6), round(percentile(diffs, 97.5), 6)


def flips(
    ids: Sequence[str], a: Sequence[int | None], b: Sequence[int | None]
) -> tuple[list[tuple[str, int, int | None]], list[tuple[str, int | None, int]]]:
    gained = [(i, x, y) for i, x, y in zip(ids, a, b, strict=True) if x is not None and y is None]
    lost = [(i, x, y) for i, x, y in zip(ids, a, b, strict=True) if x is None and y is not None]
    return gained, lost  # type: ignore[return-value]
```

`eval/verdict.py`:

```python
"""The pre-agreed win rule (spec §3). Applied mechanically; never tuned after a run."""

from collections.abc import Sequence
from dataclasses import dataclass

EPSILON = 1e-9


@dataclass(frozen=True)
class ModelScore:
    model: str
    recall: float
    mrr: float
    p95_ms: float


@dataclass(frozen=True)
class Check:
    model: str
    recall_ok: bool
    mrr_ok: bool
    latency_ok: bool

    @property
    def wins(self) -> bool:
        return self.recall_ok and self.mrr_ok and self.latency_ok


@dataclass(frozen=True)
class Verdict:
    winner: str | None
    checks: list[Check]
    line: str


def decide(
    incumbent: ModelScore,
    challengers: Sequence[ModelScore],
    *,
    margin: float = 0.05,
    max_p95_ms: float = 300.0,
) -> Verdict:
    checks = [
        Check(
            c.model,
            recall_ok=c.recall + EPSILON >= incumbent.recall + margin,
            mrr_ok=c.mrr + EPSILON >= incumbent.mrr,
            latency_ok=c.p95_ms < max_p95_ms,
        )
        for c in challengers
    ]
    winners = [c for c, check in zip(challengers, checks, strict=True) if check.wins]
    if not winners:
        return Verdict(None, checks, f"{incumbent.model} stays")
    best = max(winners, key=lambda c: (c.recall, c.mrr))
    return Verdict(best.model, checks, f"{best.model} wins → Phase 3b")
```

`EPSILON` makes 0.75 against 0.70 + 0.05 count as a pass, despite float noise. The test `0.749` still fails.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: `cd backend; uv run pytest tests/unit/test_eval_metrics.py tests/unit/test_eval_verdict.py -q`, then `cd ..; just backend::check`.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ai_second_brain/eval backend/tests/unit/test_eval_metrics.py backend/tests/unit/test_eval_verdict.py
git commit -m "feat(eval): add retrieval metrics, bootstrap and the win rule"
```

---

### Task 3: Search query space parameters

**Files:**
- Modify: `backend/src/ai_second_brain/search/query.py`, `backend/src/ai_second_brain/knowledge/embedder.py`
- Test: `backend/tests/integration/test_search_query.py` (add tests), `backend/tests/unit/test_embedder.py` (add a test, or the existing embedder unit test file)

**Interfaces:**
- Produces:
  - `query(conn, q, *, vector, folder=None, tags=(), limit=20, mode="search", terms=None, space_id: int = SPACE_ID, dims: int = SPACE_DIMS, text: bool = True)`.
  - `Embedder(url, model, dims: int | None, client, timeouts)`. When `dims=None`, any vector length is accepted, as long as every vector in one response has the same length.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/integration/test_search_query.py`, using its existing `indexed` helper:

```python
def test_default_space_uses_hnsw_index(db_url: str, tmp_path: Path, make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    VaultBuilder(tmp_path).write("a.md", "# A\nzebra")

    async def body(h: Harness) -> None:
        async with h.pool.connection() as conn:
            await conn.execute("SET enable_seqscan = off")
            plan = await (await conn.execute(
                "EXPLAIN SELECT chunk_id FROM chunk_embeddings WHERE space_id = 1"
                " ORDER BY embedding::halfvec(1024) <=> %s::halfvec(1024) LIMIT 5",
                ("[" + ",".join(["0.1"] * 1024) + "]",),
            )).fetchall()
        assert any("chunk_emb_s1_hnsw" in row[0] for row in plan)

    indexed(db_url, tmp_path, fake, body)


def test_other_space_and_text_off(db_url: str, tmp_path: Path, make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("a.md", "# A\nzebra one")
    vault.write("b.md", "# B\nzebra two")

    async def body(h: Harness) -> None:
        async with h.pool.connection() as conn:
            await conn.execute(
                "INSERT INTO embedding_spaces (id, model, dims, is_default) VALUES (101, 'tiny', 3, false)"
            )
            rows = await (await conn.execute(
                "SELECT c.id, s.external_ref FROM chunks c JOIN sources s ON s.current_revision_id = c.revision_id"
            )).fetchall()
            for chunk_id, path in rows:
                vec = "[1,0,0]" if path == "b.md" else "[0,1,0]"
                await conn.execute(
                    "INSERT INTO chunk_embeddings (chunk_id, space_id, embedding) VALUES (%s, 101, %s::halfvec)",
                    (chunk_id, vec),
                )
            vector_only = await query(conn, "zebra", vector=[1.0, 0.0, 0.0], space_id=101, dims=3, text=False)
            assert [hit.path for hit in vector_only.hits][0] == "b.md"
            assert all(hit.matched == frozenset({"vector"}) for hit in vector_only.hits)
            text_only = await query(conn, "zebra", vector=None, space_id=101, dims=3)
            assert {hit.path for hit in text_only.hits} == {"a.md", "b.md"}
            with pytest.raises(ValueError):
                await query(conn, "x", vector=None, space_id=0)

    indexed(db_url, tmp_path, fake, body)
```

Check the real `embedding_spaces` columns in `db/schema.sql`, and adjust the INSERT column list if they differ, keeping the intent.

In the embedder unit test file, use whichever fake transport that file already uses:

```python
def test_dims_none_accepts_any_consistent_length() -> None:
    ...  # a response with two 3-d vectors passes; [[1,2,3],[1,2]] raises EmbedError("embed_bad_response")
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `just backend::test tests/integration/test_search_query.py -q -k "space or hnsw"` and the embedder test.
Expected: FAIL with `TypeError: unexpected keyword 'space_id'`.

- [ ] **Step 3: Implement**

In `query()`, add the keyword parameters `space_id: int = SPACE_ID`, `dims: int = SPACE_DIMS` and `text: bool = True`. Then:

```python
    if space_id < 1 or dims < 1:
        raise ValueError("space_id and dims must be positive")
    has_text = text and (bool(q.strip()) if mode == "search" else bool(terms and terms.terms))
```

and in the `sql.SQL(_STATEMENT).format(...)` call use `dims=sql.Literal(dims), space=sql.Literal(space_id)`.

In `Embedder.__init__`, type `dims: int | None`. In `embed`, after parsing the vectors, check that they all have the same length:

```python
        vectors = [self._checked(vector) for vector in vectors]
        if len({len(v) for v in vectors}) > 1:
            raise EmbedError("embed_bad_response")
        return vectors
```

and in `_checked` replace the length condition with `len(vector) != self.dims if self.dims is not None else not vector`.

- [ ] **Step 4: Run the tests and confirm they pass**

Run: the tests above, then the full `just backend::test` and `just backend::check`.
Expected: PASS. All existing search, chat and ingest tests stay green.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ai_second_brain/search/query.py backend/src/ai_second_brain/knowledge/embedder.py backend/tests
git commit -m "feat(search): let the query target other embedding spaces"
```

---

### Task 4: The scratch database, snapshot and test fixture

**Files:**
- Create:
  - `db/eval/migrations/20261002100000_eval_cache.sql`
  - `backend/src/ai_second_brain/eval/database.py`
  - `backend/src/ai_second_brain/eval/snapshot.py`
  - `backend/tests/eval_db.py`
- Test: `backend/tests/integration/test_eval_snapshot.py`, `backend/tests/unit/test_eval_database.py`

**Interfaces:**
- Consumes: Task 1's `check_eval_url` and `EvalConfigError`.
- Produces:
  - **`database.py`:**
    - `dbmate_base(root: Path) -> list[str]` returns `shlex.split(os.environ["DBMATE"])` when that is set. Otherwise it returns `[pnpm, "--dir", str(root), "exec", "dbmate"]`, with `pnpm` resolved by `shutil.which("pnpm")`.
    - `prepare(url: str, root: Path) -> None` runs two dbmate migrations, raising `EvalConfigError` on failure.
    - `async check_ready(conn) -> None` raises `EvalConfigError(["… run just eval-prepare"])` if `eval_embedding_cache` is missing.
  - **`snapshot.py`:**
    - `SnapshotInfo(sources: int, chunks: int, taken_at: datetime)`.
    - `async snapshot(dev: AsyncConnection, ev: AsyncConnection) -> SnapshotInfo`.
    - `async live_paths(conn) -> set[str]`.
  - **Test fixture** `eval_db_url` (a pytest fixture in `tests/eval_db.py`, registered through `tests/conftest.py` imports). It:
    - creates `<test db name>_eval` on the test server (drop-and-create with `FORCE`);
    - loads `db/schema.sql`, then the eval migration's `-- migrate:up` section;
    - yields the URL.

- [ ] **Step 1: Write the migration**

`db/eval/migrations/20261002100000_eval_cache.sql`:

```sql
-- migrate:up
CREATE TABLE eval_embedding_cache (
  model        text NOT NULL,
  input_sha256 bytea NOT NULL,
  embedding    halfvec NOT NULL,
  PRIMARY KEY (model, input_sha256)
);

-- migrate:down
DROP TABLE eval_embedding_cache;
```

- [ ] **Step 2: Write the failing tests**

`backend/tests/unit/test_eval_database.py`:

```python
from pathlib import Path

import pytest

from ai_second_brain.eval import database


def test_dbmate_base_prefers_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DBMATE", "dbmate --no-dump-schema")
    assert database.dbmate_base(tmp_path) == ["dbmate", "--no-dump-schema"]


def test_prepare_runs_two_migrations(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    class Done:
        returncode = 0

    monkeypatch.setenv("DBMATE", "dbmate")
    monkeypatch.setattr(database.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or Done())
    database.prepare("postgres://u@h/x_eval", tmp_path)
    assert len(calls) == 2
    assert "--url" in calls[0] and str(tmp_path / "db" / "migrations") in calls[0]
    assert str(tmp_path / "db" / "eval" / "migrations") in calls[1]
    assert calls[1][calls[1].index("--migrations-table") + 1] == "schema_migrations_eval"
```

`backend/tests/integration/test_eval_snapshot.py`:

```python
from pathlib import Path

import psycopg
import pytest

from ai_second_brain.eval.database import check_ready
from ai_second_brain.eval.queries import EvalConfigError
from ai_second_brain.eval.snapshot import live_paths, snapshot
from ai_second_brain.vault.reconcile import reconcile

from ..conftest import run_async
from ..ingest_harness import ingest_harness
from ..vaults import VaultBuilder

pytestmark = pytest.mark.integration


def test_snapshot_copies_only_live_current(db_url: str, eval_db_url: str, tmp_path: Path, make_fake_ollama) -> None:  # type: ignore[no-untyped-def]
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("Projects/NAS.md", "---\ntags: [homelab]\n---\n# NAS\n## Dyski\nCztery dyski.")
    vault.write("gone.md", "# Gone\nx")

    async def scenario() -> None:
        async with ingest_harness(db_url, tmp_path, fake.url) as h:
            await reconcile(h.ctx, trigger="startup")
            await h.drain()
            vault.delete("gone.md")
            await reconcile(h.ctx, trigger="schedule")
        async with await psycopg.AsyncConnection.connect(db_url) as dev, \
                await psycopg.AsyncConnection.connect(eval_db_url) as ev:
            await check_ready(ev)
            info = await snapshot(dev, ev)
            assert (info.sources, info.chunks) == (1, 1)
            assert await live_paths(ev) == {"Projects/NAS.md"}
            row = await (await ev.execute(
                "SELECT c.heading_text, r.tags, c.tsv @@ websearch_to_tsquery('simple','dyski')"
                " FROM chunks c JOIN source_revisions r ON r.id = c.revision_id"
            )).fetchone()
            assert row == ("NAS Dyski", ["homelab"], True)
            again = await snapshot(dev, ev)  # idempotent: truncates first
            assert (again.sources, again.chunks) == (1, 1)
            async with dev.transaction():
                cur = await dev.execute("SELECT count(*) FROM sources WHERE deleted_at IS NULL")
                assert (await cur.fetchone()) == (1,)  # dev untouched

    run_async(scenario())


def test_check_ready_needs_cache_table(db_url: str) -> None:
    async def scenario() -> None:
        async with await psycopg.AsyncConnection.connect(db_url) as conn:
            with pytest.raises(EvalConfigError):
                await check_ready(conn)  # the test DB has no eval cache

    run_async(scenario())
```

`backend/tests/eval_db.py`:

```python
"""Create `<test db>_eval` from db/schema.sql plus the eval-only migration (no dbmate needed)."""

import re
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[2]


def _with_db(url: str, name: str) -> str:
    return urlunsplit(urlsplit(url)._replace(path=f"/{name}"))


@pytest.fixture
def eval_db_url(db_url: str) -> Iterator[str]:
    name = urlsplit(db_url).path.lstrip("/") + "_eval"
    with psycopg.connect(_with_db(db_url, "postgres"), autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.execute(f'CREATE DATABASE "{name}"')
    url = _with_db(db_url, name)
    schema = (ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
    eval_sql = (ROOT / "db" / "eval" / "migrations" / "20261002100000_eval_cache.sql").read_text(encoding="utf-8")
    up = re.split(r"--\s*migrate:down", eval_sql)[0]
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(schema)  # type: ignore[arg-type]
    with psycopg.connect(url, autocommit=True) as conn:  # schema.sql empties search_path
        conn.execute(up)  # type: ignore[arg-type]
        conn.execute("INSERT INTO embedding_spaces (id, model, dims, is_default) VALUES (1, 'bge-m3', 1024, true) ON CONFLICT DO NOTHING")
    yield url
```

Register it in `backend/tests/conftest.py` by adding `from .eval_db import eval_db_url  # noqa: F401`, or with `pytest_plugins`, whichever the repo uses.

The seed space row may already come from `schema.sql` if dbmate's dump includes data; it doesn't (schema-only). Hence the INSERT. Match `embedding_spaces`' real columns.

- [ ] **Step 3: Run the tests and confirm they fail**

Run: `cd backend; uv run pytest tests/unit/test_eval_database.py -q`, then `cd ..; just backend::test tests/integration/test_eval_snapshot.py -q`
Expected: FAIL with import errors.

- [ ] **Step 4: Implement**

`eval/database.py`:

```python
"""Prepare the scratch evaluation database with dbmate: core schema, then the eval-only cache."""

import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

from psycopg import AsyncConnection

from ai_second_brain.eval.queries import EvalConfigError


def dbmate_base(root: Path) -> list[str]:
    configured = os.environ.get("DBMATE", "").strip()
    if configured:
        return shlex.split(configured)
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        raise EvalConfigError(["pnpm not found; install it or set DBMATE to a dbmate binary"])
    return [pnpm, "--dir", str(root), "exec", "dbmate"]


def prepare(url: str, root: Path) -> None:
    base = [*dbmate_base(root), "--url", url, "--no-dump-schema"]
    runs = [
        [*base, "--migrations-dir", str(root / "db" / "migrations"), "up"],
        [*base, "--migrations-dir", str(root / "db" / "eval" / "migrations"),
         "--migrations-table", "schema_migrations_eval", "up"],
    ]
    for command in runs:
        result = subprocess.run(command, check=False, capture_output=True, text=True)  # noqa: S603
        if result.returncode != 0:
            raise EvalConfigError([f"dbmate failed (exit {result.returncode}); see its output above"])


async def check_ready(conn: AsyncConnection[Any]) -> None:
    cur = await conn.execute("SELECT to_regclass('public.eval_embedding_cache') IS NOT NULL")
    row = await cur.fetchone()
    if not row or not row[0]:
        raise EvalConfigError(["the evaluation database is not prepared: run just eval-prepare"])
```

When dbmate fails, print `result.stderr` to stderr in the CLI layer (Task 6), not in logs. Have `prepare` attach it as `error.output` on the exception so the CLI can print it.

`eval/snapshot.py`:

```python
"""Copy live, current notes from the dev DB (read-only) into the scratch DB."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from psycopg import AsyncConnection

_LIVE = "s.deleted_at IS NULL AND s.current_revision_id IS NOT NULL"
_COPIES = [
    ("sources", "id, kind, external_ref, title, sensitivity, salience, created_at",
     f"SELECT s.id, s.kind, s.external_ref, s.title, s.sensitivity, s.salience, s.created_at FROM sources s WHERE {_LIVE}"),
    ("source_revisions", "id, source_id, content_hash, raw_text, metadata, state, error, observed_at, indexed_at, tags",
     f"SELECT r.id, r.source_id, r.content_hash, '', r.metadata, r.state, r.error, r.observed_at, r.indexed_at, r.tags"
     f" FROM sources s JOIN source_revisions r ON r.id = s.current_revision_id WHERE {_LIVE}"),
    ("chunks", "id, revision_id, ordinal, heading_path, heading_text, content",
     f"SELECT c.id, c.revision_id, c.ordinal, c.heading_path, c.heading_text, c.content"
     f" FROM sources s JOIN chunks c ON c.revision_id = s.current_revision_id WHERE {_LIVE}"),
]


@dataclass(frozen=True)
class SnapshotInfo:
    sources: int
    chunks: int
    taken_at: datetime


async def snapshot(dev: AsyncConnection[Any], ev: AsyncConnection[Any]) -> SnapshotInfo:
    async with dev.transaction():
        await dev.execute("SET TRANSACTION READ ONLY")
        async with ev.transaction():
            await ev.execute("TRUNCATE sources CASCADE")
            await ev.execute("DELETE FROM embedding_spaces WHERE id >= 100")
            for table, columns, select in _COPIES:
                async with dev.cursor().copy(f"COPY ({select}) TO STDOUT") as source, \
                        ev.cursor().copy(f"COPY {table} ({columns}) FROM STDIN") as target:  # noqa: S608
                    async for block in source:
                        await target.write(block)
            await ev.execute(
                "UPDATE sources s SET current_revision_id = r.id FROM source_revisions r WHERE r.source_id = s.id"
            )
            sources = (await (await ev.execute("SELECT count(*) FROM sources")).fetchone() or (0,))[0]
            chunks = (await (await ev.execute("SELECT count(*) FROM chunks")).fetchone() or (0,))[0]
    return SnapshotInfo(sources, chunks, datetime.now(UTC))


async def live_paths(conn: AsyncConnection[Any]) -> set[str]:
    cur = await conn.execute(f"SELECT s.external_ref FROM sources s WHERE {_LIVE}")  # noqa: S608
    return {row[0] for row in await cur.fetchall()}
```

Notes for the implementer:
- Check every column list against `db/schema.sql`: the `sources`, `source_revisions` and `chunks` columns as of 2b. Don't copy generated columns (`tsv`).
- Does `TRUNCATE sources CASCADE` cascade to `source_revisions`, `chunks` and `chunk_embeddings` through their FKs? If an FK isn't `ON DELETE CASCADE`, TRUNCATE CASCADE still truncates referencing tables, so it is fine.
- `raw_text` is copied as `''`, since the evaluation doesn't need it.
- With `autocommit` off, the nested transaction blocks are real transactions.

- [ ] **Step 5: Run the tests and confirm they pass**

Run: the tests above, then the full `just backend::test` and `just backend::check`.
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add db/eval backend/src/ai_second_brain/eval backend/tests
git commit -m "feat(eval): prepare a scratch database and snapshot the vault"
```

---

### Task 5: Preflight, the embedding cache and query vectors

**Files:**
- Create: `backend/src/ai_second_brain/eval/embedding.py`
- Modify: `backend/tests/fakes/ollama.py` (`embed_topics_by_model`, `missing_models`)
- Test: `backend/tests/integration/test_eval_embedding.py`

**Interfaces:**
- Consumes:
  - `Embedder(dims=None)` (Task 3);
  - the `eval_db_url` fixture and `snapshot` (Task 4);
  - `embed_input` (2a);
  - `local_model_name` (config).
- Produces:

```python
@dataclass(frozen=True)
class ModelSpace: model: str; space_id: int; dims: int
class PreflightError(Exception): code: str; model: str
async def preflight(make_embedder: Callable[[str], Embedder], models: Sequence[str]) -> list[ModelSpace]   # space_id = 100 + i
async def embed_space(ev: AsyncConnection, embedder: Embedder, space: ModelSpace, *, batch: int,
                      progress: Callable[[str, int, int], None]) -> int   # returns number newly embedded
async def query_vectors(embedder: Embedder, texts: Sequence[str]) -> tuple[list[list[float]], list[float]]  # vectors, per-text ms (after one warm-up)
async def model_digests(client: httpx2.AsyncClient, url: str, models: Sequence[str]) -> dict[str, str]  # "unknown" when unavailable
```

- [ ] **Step 1: Extend the fake Ollama**

Add to the fake's behaviour dataclass:

```python
    embed_topics_by_model: dict[str, dict[str, str]] = field(default_factory=dict)
    missing_models: set[str] = field(default_factory=set)
```

In `_embed`:
- if `body["model"] in b.missing_models`, return `JSONResponse({"error": f'model "{body["model"]}" not found, try pulling it first'}, status_code=404)`;
- otherwise choose `topics = b.embed_topics_by_model.get(body["model"], b.embed_topics)` and use it in `vector_for`;
- make the topic vector depend on the model too: `fake_vector(f"topic:{body['model']}:{topic}")`, so spaces differ.

Keep the existing `embed_topics` behaviour unchanged for 2b tests: when `embed_topics_by_model` is empty, use the old `f"topic:{topic}"` key. Run the 2b search tests to confirm.

- [ ] **Step 2: Write the failing tests**

`backend/tests/integration/test_eval_embedding.py` uses `ingest_harness` to index a vault into the test DB, then `snapshot` into `eval_db_url`, then:

```python
def test_cache_reuse_edit_and_resume(db_url, eval_db_url, tmp_path, make_fake_ollama) -> None:  # type: ignore[no-untyped-def]
    # vault with 3 notes → index → snapshot
    # space = (await preflight(make, ["m1"]))[0]; assert space == ModelSpace("m1", 100, 1024)
    # first = await embed_space(ev, emb, space, batch=2, progress=noop); assert first == 3
    # assert count(chunk_embeddings where space_id=100) == 3
    # calls = len(fake.embed_requests()); again = await embed_space(...); assert again == 0
    # assert len(fake.embed_requests()) == calls  (no embed calls; cache hit)
    # edit one note in the vault → reconcile+drain in dev → snapshot → embed_space returns 1


def test_interrupted_embedding_resumes(db_url, eval_db_url, tmp_path, make_fake_ollama) -> None:  # type: ignore[no-untyped-def]
    # 5 notes, batch=2; fake.behaviour.embed_fail_on_call = 2 → embed_space raises EmbedError
    # cache holds exactly 2 rows for the model; clear the failure; rerun → returns 3; total cache rows 5


def test_preflight_missing_model(make_fake_ollama) -> None:  # type: ignore[no-untyped-def]
    # fake.behaviour.missing_models = {"ghost"}; preflight(make, ["m1", "ghost"]) raises PreflightError
    # with code "embed_model_missing" and model "ghost"; no snapshot needed


def test_query_vectors_and_latency(make_fake_ollama) -> None:  # type: ignore[no-untyped-def]
    # vectors, ms = await query_vectors(emb, ["a", "b"]); len(vectors) == 2 == len(ms); all ms >= 0
    # the fake recorded 3 embed calls (1 warm-up + 2), each with keep_alive == "30m"


def test_model_digests_unknown_when_unavailable(make_fake_ollama) -> None:  # type: ignore[no-untyped-def]
    # fake has no /api/tags route (404) → {"m1": "unknown"}
```

Write each comment line as real code with real assertions. Use `ingest_harness`, `reconcile` and `h.drain()` exactly as `test_eval_snapshot.py` does. `make` is `lambda model: Embedder(fake.url, model, None, client, FAST)`, using `create_http_client()` and `FAST` from `tests/ingest_harness.py`. If the fake already serves `/api/tags`, use a model name it doesn't list.

- [ ] **Step 3: Run the tests and confirm they fail**

Run: `just backend::test tests/integration/test_eval_embedding.py -q`
Expected: FAIL with an import error.

- [ ] **Step 4: Implement `eval/embedding.py`**

```python
"""Embed the scratch snapshot per model with a resumable cache; time query embeddings."""

import hashlib
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import httpx2
from psycopg import AsyncConnection

from ai_second_brain.config import local_model_name
from ai_second_brain.knowledge.embed_text import embed_input
from ai_second_brain.knowledge.embedder import Embedder, EmbedError

KEEP_ALIVE = "30m"
SPACE_BASE = 100


@dataclass(frozen=True)
class ModelSpace:
    model: str
    space_id: int
    dims: int


class PreflightError(Exception):
    def __init__(self, code: str, model: str) -> None:
        super().__init__(f"{code}: {model}")
        self.code, self.model = code, model


async def preflight(make_embedder: Callable[[str], Embedder], models: Sequence[str]) -> list[ModelSpace]:
    spaces: list[ModelSpace] = []
    for index, model in enumerate(models):
        try:
            local_model_name(model)
        except ValueError:
            raise PreflightError("cloud_model_refused", model) from None
        try:
            [vector] = await make_embedder(model).embed(["preflight"], keep_alive=KEEP_ALIVE)
        except EmbedError as error:
            raise PreflightError(error.code, model) from None
        spaces.append(ModelSpace(model, SPACE_BASE + index, len(vector)))
    return spaces


def _digest(text: str) -> bytes:
    return hashlib.sha256(text.encode("utf-8")).digest()


async def embed_space(
    ev: AsyncConnection[Any],
    embedder: Embedder,
    space: ModelSpace,
    *,
    batch: int,
    progress: Callable[[str, int, int], None],
) -> int:
    rows = await (await ev.execute(
        "SELECT c.id, s.title, c.heading_path, c.content FROM chunks c"
        " JOIN sources s ON s.current_revision_id = c.revision_id ORDER BY c.id"
    )).fetchall()
    inputs = [(chunk_id, embed_input(title or "", heading_path, content)) for chunk_id, title, heading_path, content in rows]
    keys = [(chunk_id, _digest(text)) for chunk_id, text in inputs]
    cached = {row[0] for row in await (await ev.execute(
        "SELECT input_sha256 FROM eval_embedding_cache WHERE model = %s", (space.model,)
    )).fetchall()}
    todo: dict[bytes, str] = {}
    for (_, key), (_, text) in zip(keys, inputs, strict=True):
        if key not in cached:
            todo.setdefault(key, text)
    items = list(todo.items())
    for start in range(0, len(items), batch):
        chunk = items[start : start + batch]
        vectors = await embedder.embed([text for _, text in chunk], keep_alive=KEEP_ALIVE)
        async with ev.transaction():
            async with ev.cursor() as cur:
                await cur.executemany(
                    "INSERT INTO eval_embedding_cache (model, input_sha256, embedding)"
                    " VALUES (%s, %s, %s::halfvec) ON CONFLICT DO NOTHING",
                    [(space.model, key, "[" + ",".join(map(repr, vec)) + "]") for (key, _), vec in zip(chunk, vectors, strict=True)],
                )
        progress(space.model, min(start + batch, len(items)), len(items))
    async with ev.transaction():
        await ev.execute(
            "INSERT INTO embedding_spaces (id, model, dims, is_default) VALUES (%s, %s, %s, false)"
            " ON CONFLICT (id) DO UPDATE SET model = EXCLUDED.model, dims = EXCLUDED.dims",
            (space.space_id, space.model, space.dims),
        )
        await ev.execute("DELETE FROM chunk_embeddings WHERE space_id = %s", (space.space_id,))
        async with ev.cursor() as cur:
            await cur.executemany(
                "INSERT INTO chunk_embeddings (chunk_id, space_id, embedding)"
                " SELECT %s, %s, embedding FROM eval_embedding_cache WHERE model = %s AND input_sha256 = %s",
                [(chunk_id, space.space_id, space.model, key) for chunk_id, key in keys],
            )
    return len(items)


async def query_vectors(embedder: Embedder, texts: Sequence[str]) -> tuple[list[list[float]], list[float]]:
    await embedder.embed(["warm-up"], keep_alive=KEEP_ALIVE)
    vectors: list[list[float]] = []
    timings: list[float] = []
    for text in texts:
        started = time.perf_counter()
        [vector] = await embedder.embed([text], keep_alive=KEEP_ALIVE)
        timings.append((time.perf_counter() - started) * 1000)
        vectors.append(vector)
    return vectors, timings


async def model_digests(client: httpx2.AsyncClient, url: str, models: Sequence[str]) -> dict[str, str]:
    digests = dict.fromkeys(models, "unknown")
    try:
        response = await client.get(f"{url}/api/tags", timeout=5.0)
        listed = {m.get("name"): m.get("digest") for m in response.json().get("models", [])} if response.status_code == 200 else {}
    except (httpx2.HTTPError, ValueError, AttributeError):
        return digests
    for model in models:
        digest = listed.get(model) or listed.get(f"{model}:latest")
        if isinstance(digest, str):
            digests[model] = digest
    return digests
```

Use the real `embedding_spaces` columns; check whether there is an `is_default` column and a unique constraint on it. If inserting into `chunk_embeddings` row by row with `executemany` is slow for large vaults, replace it with one `INSERT … SELECT` from a temp table filled by `COPY` (`chunk_id, input_sha256`). The tests don't change.

- [ ] **Step 5: Run the tests and confirm they pass**

Run: `just backend::test tests/integration/test_eval_embedding.py -q`, the 2b search tests (to check the fake's backward compatibility), the full `just backend::test`, and `just backend::check`.
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ai_second_brain/eval/embedding.py backend/tests
git commit -m "feat(eval): embed snapshots per model with a resumable cache"
```

---

### Task 6: Runner, report and CLI

**Files:**
- Create:
  - `backend/src/ai_second_brain/eval/runner.py`
  - `backend/src/ai_second_brain/eval/report.py`
  - `backend/tests/fixtures/eval/queries.yaml`
- Modify: `backend/src/ai_second_brain/interfaces/cli/main.py`, root `justfile`
- Test:
  - `backend/tests/unit/test_eval_report.py`
  - `backend/tests/integration/test_eval_run.py`
  - `backend/tests/unit/test_cli_eval.py`

**Interfaces:**
- Consumes everything above.
- Produces:

```python
@dataclass(frozen=True)
class ModelRun:
    model: str; space_id: int; dims: int; digest: str; newly_embedded: int
    hybrid: list[int | None]; vector: list[int | None]      # first-target ranks per query (query order)
    hybrid_paths: list[list[str]]; vector_paths: list[list[str]]
    latency_ms: list[float]
@dataclass(frozen=True)
class RunResult:
    snapshot: SnapshotInfo; queries: list[EvalQuery]; queries_sha256: str; queries_path: str
    models: list[ModelRun]; text_only: list[int | None]; text_only_paths: list[list[str]]
    verdict: Verdict; intervals: dict[str, tuple[float, float]]
async def run_eval(settings: Settings, *, queries_path: Path, models: Sequence[str],
                   dev_url: str, eval_url: str, test_url: str | None,
                   client: httpx2.AsyncClient, progress: Callable[[str], None]) -> RunResult
def render_markdown(result: RunResult) -> str
def write_report(result: RunResult, out_dir: Path, now: datetime) -> Path   # returns the run folder
```

- **CLI:** `ai-second-brain eval prepare`, `eval suggest [--n 60]`, `eval check [--queries PATH]`, and `eval run [--models a,b] [--out DIR] [--queries PATH]`.
- **Root `justfile` recipes:**

```just
# Create/migrate the scratch evaluation database (SB_EVAL_DATABASE_URL)
eval-prepare:
    uv run --directory backend ai-second-brain eval prepare

# Print a starter queries.yaml (redirect it into SB_EVAL_QUERIES and edit)
eval-suggest *args:
    uv run --directory backend ai-second-brain eval suggest {{ args }}

# Validate the query set against the current index
eval-check *args:
    uv run --directory backend ai-second-brain eval check {{ args }}

# Run the embedding bake-off and write a report to SB_EVAL_DIR
eval-run *args: eval-prepare
    uv run --directory backend ai-second-brain eval run {{ args }}
```

- [ ] **Step 1: Write the synthetic fixture and the failing tests**

`backend/tests/fixtures/eval/queries.yaml`:

```yaml
version: 1
queries:
  - {id: backup-paraphrase, q: "nightly backup schedule", lang: en, kind: paraphrase, targets: [Projects/NAS.md]}
  - {id: disks-identifier, q: "RAID 5", lang: en, kind: identifier, targets: [Projects/NAS.md]}
  - {id: proxmox-topic, q: "klaster wirtualizacji", lang: pl, kind: topic, targets: [Projects/Proxmox.md]}
```

`backend/tests/integration/test_eval_run.py` builds a tmp vault. It has `Projects/NAS.md` (`# NAS\n## Dyski\nCztery dyski w RAID 5.\n## Kopie zapasowe\nCo noc o 02:00.`), `Projects/Proxmox.md` (`# Proxmox\nKlaster z jednym węzłem.`) and 12 filler notes `Filler/f{i}.md` (`# F{i}\nfiller text {i}`). It indexes them, then calls `run_eval` with two fake models:
- `"bge-m3"` with topics `{"filler": "decoy", "backup": "decoy", "wirtualizacji": "decoy"}`. The decoy-mapped queries pull 12 fillers into the top 10, so NAS and Proxmox miss for the paraphrase and topic queries.
- `"good-model"` with topics `{"backup": "backup", "kopie zapasowe": "backup", "wirtualizacji": "virt", "klaster": "virt"}`. These map queries onto their target notes.

```python
def test_full_run_writes_report_and_picks_winner(db_url, eval_db_url, tmp_path, make_fake_ollama) -> None:  # type: ignore[no-untyped-def]
    # index vault → settings = Settings(DATABASE_URL=db_url, eval_dir=tmp_path/"reports", SB_EVAL_DATABASE_URL=eval_db_url, embed_url_override=fake.url, ...)
    # result = await run_eval(settings, queries_path=FIXTURE, models=["bge-m3", "good-model"], dev_url=db_url,
    #                         eval_url=eval_db_url, test_url=None, client=client, progress=lambda _: None)
    # assert result.verdict.winner == "good-model"
    # assert result.models[0].hybrid[1] == 1 (RAID 5 found by text for both: identifier query)
    # assert result.models[1].hybrid[0] == 1 and result.models[0].hybrid[0] is None
    # folder = write_report(result, settings.eval_report_dir, datetime(2026, 10, 2, 12, 0, 0))
    # assert folder.name == "20261002-120000"
    # md = (folder / "report.md").read_text(); assert "good-model wins → Phase 3b" in md
    # assert "nightly backup schedule" not in md          # report shows ids, never query text
    # data = json.loads((folder / "results.json").read_text()); assert data["version"] == 1
    # assert data["queries"][0]["runs"]["good-model"]["hybrid"][0] == "Projects/NAS.md"


def test_run_refuses_dev_url(db_url, tmp_path) -> None:  # type: ignore[no-untyped-def]
    # run_eval(..., eval_url=db_url.replace("127.0.0.1", "localhost"), dev_url=db_url) raises EvalConfigError
    # and nothing is written (no reports dir created)


def test_missing_target_is_config_error(db_url, eval_db_url, tmp_path, make_fake_ollama) -> None:  # type: ignore[no-untyped-def]
    # a queries file whose target is not in the vault → EvalConfigError naming that query id


def test_run_logs_no_query_text(db_url, eval_db_url, tmp_path, make_fake_ollama, caplog) -> None:  # type: ignore[no-untyped-def]
    # caplog.set_level(logging.DEBUG); full run; for each query q in the fixture: q not in caplog.text
```

Write every comment as real code. The fake's per-model topics apply to the query text and to the chunk inputs alike. Filler chunk inputs contain "filler", so under `bge-m3` the query "nightly backup schedule" maps to `decoy`, and all 12 fillers have similarity 1 and take the top 10. The text side doesn't match NAS, because "nightly", "backup" and "schedule" don't appear in it. NAS therefore misses under `bge-m3`. Proxmox likewise: "klaster wirtualizacji" in AND mode needs both words, and "wirtualizacji" isn't in the note.

`backend/tests/unit/test_eval_report.py` builds a small `RunResult` by hand and checks that `render_markdown` contains:
- the verdict line;
- a summary table row per model and run type, with recall formatted as a percentage and one decimal;
- the latency table (p50 and p95);
- the per-condition check table with ✓/✗;
- the bootstrap interval;
- the `lang` and `kind` splits;
- the flips by query id;
- the snapshot counts;
- each model's digest;
- the queries file SHA-256.

It must contain no query text.

`backend/tests/unit/test_cli_eval.py` uses Typer's `CliRunner` with `run_eval` and `prepare` monkeypatched. It checks:
- `eval run` exits 0 with the verdict line on stdout;
- it exits 1 on `EvalConfigError`, printing each error line to stderr;
- it exits 1 on `PreflightError("embed_model_missing", "ghost")`, printing `ollama pull ghost`;
- it exits 2 on an unexpected `RuntimeError`, printing only the type name;
- `eval suggest` prints YAML that `yaml.safe_load` parses into `version: 1` with entries whose `q` is empty;
- `eval check` exits 1 on an empty `q`, with the hint "write a question".

For suggest and check, monkeypatch the DB-reading helpers.

- [ ] **Step 2: Run the tests and confirm they fail**

Run: the three test files.
Expected: FAIL.

- [ ] **Step 3: Implement**

`eval/runner.py` follows spec §6:
1. `check_eval_url(eval_url, dev_url, test_url)` runs before anything else.
2. `load_queries(queries_path)`.
3. `preflight` with `make_embedder = lambda m: Embedder(settings.embed_url, m, None, client, ChatTimeouts())`. If `settings.embed_url` is None, raise `EvalConfigError(["no embedding host: set SB_EMBED_URL"])`.
4. Open the dev and eval connections (`AsyncConnection.connect`), then `check_ready(ev)`, then `snapshot(dev, ev)`.
5. Check the targets against `live_paths(ev)`, collecting `"{id}: target not in the index: {path}"`, and raise `EvalConfigError` if any are missing. Paths may appear in this error, which is shown on the owner's terminal only and never logged.
6. For each space:
   - `embed_space(ev, embedder, space, batch=settings.embed_batch, progress=…)`, where progress prints `"{model} {done}/{total}"`;
   - `query_vectors(embedder, [q.q for q in queries])`;
   - per query, `query(ev, q.q, vector=v, space_id=..., dims=..., limit=10)` for hybrid, and the same with `text=False` for vector-only;
   - ranked paths come from `dict.fromkeys(hit.path for hit in result.hits)`.
7. text-only runs once per query: `query(ev, q.q, vector=None, limit=10)`.
8. Compute `first_rank` per run. Build `ModelScore`s from `summarize(hybrid)` and `percentile(latency_ms, 95)`. Then `decide(incumbent=models[0], challengers=models[1:])`. Compute `intervals[model] = bootstrap_diff(model.hybrid, incumbent.hybrid)`.
9. `model_digests(client, settings.embed_url, models)`.
10. Log only `eval run models=%d queries=%d chunks=%d ms=%d`.

`eval/report.py`:
- `render_markdown` produces the sections listed in spec §7.4, in that order, using GitHub tables. Percentages are formatted as `f"{x * 100:.1f}%"`.
- `write_report`:
  - creates `out_dir / now.strftime("%Y%m%d-%H%M%S")` (`exist_ok=False`, adding `-2` on a collision);
  - writes `report.md` and `results.json` (UTF-8, `ensure_ascii=False`, `indent=2`) with the shape in spec §7.4, where the lists hold paths;
  - returns the folder.

CLI, in `interfaces/cli/main.py`. Add an `eval_app = typer.Typer(no_args_is_help=True, help="Embedding evaluation commands.")` registered as `eval`, mirroring `vault_app`:
- **`prepare`:** calls `prepare(settings.eval_database_url, REPO_ROOT)` after `check_eval_url(..., os.environ.get("TEST_DATABASE_URL"))`. It prints "Evaluation database ready." On `EvalConfigError`, it prints the errors and any dbmate output to stderr and exits 1.
- **`suggest --n`:** samples live notes from the dev DB, stratified by top-level folder. It uses SQL `row_number() OVER (PARTITION BY split_part(external_ref, '/', 1) ORDER BY random())`, then picks round-robin across folders until `n`. It prints `yaml.safe_dump({"version": 1, "queries": [...]}, allow_unicode=True, sort_keys=False)`, with ids `q01`, `q02`, … and `q: ""`, `lang: pl`, `kind: topic`, `targets: [path]`.
- **`check --queries`:** loads the queries, then checks their targets against the dev DB's live paths. It prints the totals and the counts by `lang` and `kind`. It exits 1 with all errors on failure.
- **`run --models --out --queries`:** builds the settings, model list and paths. It calls `asyncio.run(run_eval(...), loop_factory=new_event_loop)` inside `async with create_http_client()`, then writes the report. It prints the verdict line, a compact summary table and the report path.
  - It exits 1 on `EvalConfigError` or `PreflightError`. For `embed_model_missing` it prints `Model {model} is not installed: run ollama pull {model}`; for other preflight codes it prints the code.
  - It exits 2 on anything else, printing `Evaluation failed ({type(error).__name__}).`

Add the four recipes above to the root `justfile`. Also add them to the README command table in Task 7.

- [ ] **Step 4: Run the tests and confirm they pass**

Run the new tests, then the full `just backend::test` and `just check`.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend justfile
git commit -m "feat(eval): run the embedding bake-off and write a report"
```

---

### Task 7: Docs and final checks

**Files:**
- Modify: `README.md`, `docs/architecture/adr/0006-embedding-spaces.md`, `docs/architecture/system-design.md` §9, `.env.example`

- [ ] **Step 1: README**

Add an "Evaluating search" section after the Search/Capture docs, matching the README's voice. It covers:
- **Purpose:** what the bake-off decides, and that its result is pending your run.
- **Steps:**
  1. `just eval-suggest > ~/.second-brain/eval/queries.yaml`;
  2. write a question for each entry. Write some `paraphrase` ones without the note open, and drop entries you can't phrase;
  3. `just eval-check`;
  4. `just eval-run`.
- **The YAML format:** one example entry, plus the meaning of `lang` and `kind`.
- **The win rule**, verbatim from the Global Constraints.
- **Files:** where reports go, and that the queries file and reports are private: outside the repo, and never committed.
- **Models:** they must be pulled (`ollama pull snowflake-arctic-embed2` and so on). The first run embeds the whole vault once per model; the CLI prints an ETA. Later runs reuse the cache.
- **Settings:** the four `SB_EVAL_*` rows in the settings table.
- **Commands table:** the four `just eval-*` commands in the everyday-commands table.
- **Repository layout:** `backend/src/ai_second_brain/eval/` and `db/eval/migrations/`.

- [ ] **Step 2: ADR, system design, `.env.example`**

- **ADR-0006:** add a "Phase 3 (2026-10-02)" note. It says the bake-off harness exists, links the spec, and states the candidate list and the win rule. It records the result as "pending the owner's first run".
- **`system-design.md` §9:** Phase 3 is **delivered (harness)**, with a link to the spec. Add a row "3b — Switch embedding space (only if a challenger wins)", depending on 3.
- **`.env.example`:** add the four settings, commented out, with their defaults.

- [ ] **Step 3: Final verification**

Run from the repo root: `just check`, `just test`, `just e2e`.
Expected: all pass. The owner step: write the queries, then `just eval-check` and `just eval-run`.

- [ ] **Step 4: Commit**

```bash
git add README.md docs .env.example
git commit -m "docs: document the embedding bake-off"
```

The owner pushes once after the final whole-branch review. CI releases v0.6.0.

# Phase 3: embedding evaluation (bake-off against bge-m3)

Date: 2026-10-02 · Status: **approved design, spec under review** · Owner: Michal Dyzma
Parent docs: [system design](../../architecture/system-design.md) §9 · [ADR-0006](../../architecture/adr/0006-embedding-spaces.md) · builds on [Phase 2b](2026-10-01-phase-2b-search-retrieval-capture-design.md)

## 1. Purpose and success

Phase 3 decides, with a measurement rather than an opinion, whether bge-m3 should remain the default embedding model. It builds a reusable evaluation harness. The harness embeds a snapshot of the owner's indexed vault with each candidate model in a scratch database. It then runs a labelled query set, written by the owner, through the production search code, and applies a win rule fixed in advance.

Phase 3 ships the harness and the report only. If a challenger wins, switching models is a separate Phase 3b with its own spec: a second production space, a resumable backfill, and flipping the default.

**Success (exit criteria):**
1. With the owner's `queries.yaml`, `just eval-run` embeds the vault snapshot with the four candidate models in a scratch database. It writes `report.md` and `results.json`, and the report contains the verdict.
2. Production data, schema and search behaviour are unchanged. The default `search.query()` path still uses the HNSW index.
3. A second run reuses cached vectors and embeds only new or changed chunks. An interrupted run resumes.
4. Unit and integration tests pass. CI releases v0.6.0.

Writing the query set (about 50 queries) and running the bake-off are owner steps after release. The outcome decides whether Phase 3b happens.

## 2. Scope

**In:**
- the query-set format, loader and checker;
- the `eval suggest`, `eval check` and `eval run` CLI commands, with `just` recipes;
- the scratch evaluation database and its own migration;
- snapshotting;
- embedding with a cache;
- the generalised `search.query()` space parameters;
- metrics, a paired bootstrap and the verdict;
- the report files;
- tests and docs.

**Out:**
- Phase 3b work: a production second space, a backfill job, and switching the default;
- similarity-floor tuning, re-ranking and the salience evaluation (the harness supports them later);
- any web UI;
- LLM-generated queries;
- cloud embeddings (never).

## 3. Candidates and the win rule

Candidates (the default list, overridable with `--models`):

| Model (Ollama tag) | Role |
|---|---|
| `bge-m3` | incumbent, the baseline to beat |
| `snowflake-arctic-embed2` | strong multilingual challenger |
| `granite-embedding:278m` | small multilingual challenger |
| `paraphrase-multilingual` | weak baseline |

The incumbent is the model given as `SB_EMBED_MODEL`, for example `bge-m3:567m`. Its run is labelled with that exact tag. Every model must pass `local_model_name`, so `:cloud` and `-cloud` tags are refused.

**Win rule.** It is fixed before any run, applied automatically, and not changed afterwards. A challenger **wins** only if all three hold:
1. its hybrid recall@10 ≥ the incumbent's hybrid recall@10 + 0.05 (5 percentage points);
2. its hybrid MRR@10 ≥ the incumbent's hybrid MRR@10;
3. its query-embedding p95 < 300 ms on the owner's embedding host.

If several challengers win, the one with the highest hybrid recall@10 is named, with ties broken by MRR@10. The verdict line reads either `bge-m3 stays` or `<model> wins → Phase 3b`.

## 4. Settings

All `SB_*` settings are validated in `config.py`.

| Variable | Default | Rule |
|---|---|---|
| `SB_EVAL_QUERIES` | `~/.second-brain/eval/queries.yaml` | A path, with `~` expanded. It is read only by the `eval` commands. |
| `SB_EVAL_DIR` | `~/.second-brain/eval/reports` | The report directory, created if missing. It must not be inside the repository. Refuse a path under `REPO_ROOT`. |
| `SB_EVAL_DATABASE_URL` | `DATABASE_URL` with the database name suffixed `_eval` | Must differ from `DATABASE_URL` and from `TEST_DATABASE_URL`. The CLI refuses to run otherwise. |
| `SB_EVAL_MODELS` | `bge-m3,snowflake-arctic-embed2,granite-embedding:278m,paraphrase-multilingual` | Comma-separated Ollama tags. The first must be the incumbent, which is replaced by `SB_EMBED_MODEL`'s exact tag when it is a tag of the same model. |

Embedding uses `settings.embed_url` (from 2a), `SB_EMBED_BATCH`, and the existing `Embedder`. Nothing leaves the LAN.

## 5. The query set

### 5.1 Format (`queries.yaml`)

```yaml
version: 1
queries:
  - id: nas-backup-time         # [a-z0-9-]{1,64}, unique
    q: "o której idą kopie zapasowe NAS?"   # 1–500 characters
    lang: pl                    # pl | en
    kind: paraphrase            # identifier | paraphrase | topic
    targets: [Projects/NAS.md]  # 1–10 vault-relative paths; a hit on any one counts
```

### 5.2 Loader (`eval/queries.py`)

`load_queries(path) -> list[EvalQuery]` uses `yaml.safe_load` and checks:
- the version is 1;
- the ids are unique and match the pattern;
- the fields have the right types and ranges.

`resolve_targets(conn, queries)` checks that every target is a live note in the snapshot. Errors are collected and raised together as `EvalConfigError`. Each error carries the query **id**, the field and the reason. Paths may appear in these errors, which are shown on the owner's terminal only. Query text never appears in errors or logs.

### 5.3 Commands

- **`ai-second-brain eval suggest [--n 60]`** prints a starter YAML to stdout:
  - it samples `n` live notes across folders, stratified by top-level folder;
  - each sampled note gets an entry with `targets` filled in and `q: ""`, `lang: pl`, `kind: topic`;
  - it never writes a file.
- **`ai-second-brain eval check`** runs the loader and target resolution against the dev database. It prints counts by `lang` and `kind` and exits 1 on any error. An empty `q` is an error with the hint "write a question".
- **`ai-second-brain eval run [--models a,b,…] [--out DIR] [--queries PATH]`** runs the pipeline in §6 and the report in §7.
- **`just` recipes:**
  - `eval-suggest` and `eval-check`;
  - `eval-run`, which depends on `db::eval-prepare`.

## 6. The run pipeline

### 6.1 The scratch database

- `db/justfile` gains `eval-prepare`, mirroring `test-prepare`. It creates `SB_EVAL_DATABASE_URL`'s database if it is missing, then runs dbmate twice:
  - with the normal `db/migrations`;
  - with `db/eval/migrations`, which uses its own migrations table `schema_migrations_eval`. Check the dbmate flag for this (`--migrations-table`).
- `db/eval/migrations/<ts>_eval_cache.sql` is the scratch-only migration:

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

- **Run guards.** Before writing anything, `eval run` checks two things:
  1. the eval URL differs from both the dev and test URLs, compared after normalising host, port and database name;
  2. `eval_embedding_cache` exists.

  If either check fails, it exits 1 with `run just eval-prepare`.

### 6.2 Snapshot

In the eval database, one transaction does the following:
1. truncates `chunk_embeddings`, `chunks`, `source_revisions` and `sources` (CASCADE), plus the `embedding_spaces` rows other than the seed;
2. copies from the dev database, which is opened read-only (`SET TRANSACTION READ ONLY`):
   - live sources (`deleted_at IS NULL AND current_revision_id IS NOT NULL`);
   - their current revisions;
   - those revisions' chunks.

Ids, `heading_text`, tags and generated `tsv` all match production. Use `COPY … TO STDOUT` / `COPY … FROM STDIN` through psycopg, without exposing generated columns.

The snapshot time and the source and chunk counts go into the report.

### 6.3 Spaces and embedding

**Spaces.** Model `i` in the run order gets `embedding_spaces` row id `100 + i`. The model is its tag and `dims` comes from its first vector. These are scratch-only rows. Ids from 100 upwards avoid the seeded space 1.

**Embedding.**
- Each chunk's input is `embed_input(title, heading_path, content)`, the same function the indexer uses.
- The key is `input_sha256 = sha256(input)`.
- Missing keys are embedded in batches of `SB_EMBED_BATCH`, with `keep_alive="30m"`. Each batch is upserted into the cache and committed, so an interrupted run resumes.
- When every key for a model is present, its `chunk_embeddings` rows (`space_id = 100 + i`) are written from the cache.

**Progress** goes to stdout: model tag, done/total, chunks per second, and an ETA after the first 3 batches. Progress shows counts only.

**Preflight**, before any embedding:
- every tag passes `local_model_name`;
- a 1-text test embed succeeds;
- the dims are consistent.

A missing model (`embed_model_missing`) fails with `ollama pull <tag>`. If the host is unreachable, the run fails with that code.

### 6.4 Generalised search

`search.query()` gains two keyword parameters, `space_id: int = SPACE_ID` and `dims: int = SPACE_DIMS`. Both are inlined as SQL literals and validated as positive ints.

- Production callers don't pass them.
- A test pins that the default statement still uses `chunk_emb_s1_hnsw`, via EXPLAIN on the test database.
- In the eval database there is no HNSW index on spaces ≥ 100, so vector ranking there is exact.

### 6.4a Query prompts and cache identity (added during the final review)

- **Query prefixes.** Each candidate's query text gets the prefix its model card prescribes. Note text never gets a prefix. Today only `snowflake-arctic-embed2` has one: `query: `. bge-m3, granite-embedding and paraphrase-multilingual use none. The same prefixed text is used for the latency timing and for the ranking vector. The report and `results.json` list each model's prefix. **If a prefixed model ever wins, Phase 3b must apply the same query prefix in production search and chat**; otherwise production quality will be lower than the bake-off measured.
- **Cache identity.** The cache's `model` column stores `<tag>@<digest>`, using the digest from Ollama `/api/tags`, or the bare tag when the digest is unknown. A re-pulled model is therefore re-embedded instead of being scored with stale vectors. Spaces and report labels use the plain tag.

### 6.5 Query runs

For each model and each query, with `limit=10` and `mode="search"`:
- **hybrid** runs the query text plus its vector;
- **vector-only** runs the vector alone, with full-text disabled. Add an explicit `text: bool = True` parameter to `query()` rather than passing an empty `q`.

**text-only** (`vector=None`) runs once per query.

Each run records the ranked list of distinct `source_id`s, which is at most 10.

### 6.6 Latency

For each model:
- one warm-up embed;
- then each query text embedded once, alone, with `keep_alive`;
- the p50 and p95 wall-clock times are recorded.

## 7. Metrics, uncertainty, verdict and report

### 7.1 Metrics (`eval/metrics.py`, pure)

The metrics are computed per model and per run type over notes, not chunks:
- **recall@10:** the share of queries with any target among the first 10 notes;
- **MRR@10:** the mean of `1/rank` of the first target note, or 0 when there is none;
- **hit@1:** the share of queries whose first note is a target.

Each metric is computed overall and split by `lang` and by `kind`.

### 7.2 Uncertainty

**Paired bootstrap** over queries: 2,000 resamples with `random.Random(20261002)`. For each challenger it gives a 95% percentile interval for its hybrid recall@10 minus the incumbent's.

**Flips:** query ids where the challenger has a target in the top 10 and the incumbent doesn't, and the reverse, each with both ranks.

### 7.3 Verdict (`eval/verdict.py`, pure)

The verdict applies §3 exactly. It returns, per challenger, whether each of the three conditions passed and the winner, if any.

### 7.4 Report

Output goes to `SB_EVAL_DIR/<YYYYMMDD-HHMMSS>/`:
- **`report.md`**, with these sections:
  - the verdict line;
  - the summary table (model × run type × recall@10, MRR@10, hit@1);
  - the latency table;
  - the per-condition verdict table, including the bootstrap interval;
  - the splits by `lang` and `kind`;
  - the flips (query ids and ranks, no text);
  - the snapshot counts and time, plus each model's tag and digest (from Ollama `/api/show`; record "unknown" when unavailable);
  - the queries file path and its SHA-256.
- **`results.json`:** `{version: 1, snapshot, models, queries: [{id, lang, kind, targets, runs: {<model>: {hybrid: [paths], vector: [paths], latency_ms}}, text_only: [paths]}]}`.

The CLI prints the verdict line and the summary table to stdout.

**Exit codes:**
- 0 when the run completes, whatever the verdict;
- 1 on a config or preflight error;
- 2 on a runtime failure.

## 8. Privacy and logging

- **Logs:** they carry only counts, model tags, durations and error codes. They never carry query text, note text, paths or targets.
- **Private files:** the queries file and the reports name the owner's notes. They live outside the repository by default, and `SB_EVAL_DIR` refuses repository paths.
- **Database access:** the dev database is read inside a read-only transaction, and nothing is written to it.
- **Test fixtures:** the repository contains only `backend/tests/fixtures/eval/queries.yaml`, synthetic queries over the e2e fixture vault.

## 9. Testing

### 9.1 Unit tests (no database)

- **Loader:** valid file; duplicate id; a bad id pattern; an empty `q`; unknown `lang` and `kind`; target-count limits; version ≠ 1; non-YAML input. Every error names its query id.
- **Metrics:** hand-made ranked lists, including duplicates of one note (counted once), no hit, a hit at rank 10 against rank 11, and multiple targets.
- **Bootstrap:** a fixed seed gives a fixed interval; identical runs give an interval of [0, 0].
- **Verdict:** each condition fails alone; several winners resolve by the tie rule.
- **Settings:**
  - the eval URL default derivation;
  - refusal when the eval URL equals the dev or test URL;
  - refusal of an `SB_EVAL_DIR` inside the repository;
  - `SB_EVAL_MODELS` parsing, including the incumbent replaced by `SB_EMBED_MODEL`'s tag;
  - `:cloud` tags refused.

### 9.2 Integration tests (Postgres and the fake Ollama)

The fake Ollama gains per-model topic maps, so two fake models rank differently.

1. The snapshot copies only live, current data, and its counts match.
2. The default `query()` still uses `chunk_emb_s1_hnsw`. With `space_id=101, dims=…` it returns results for that space only.
3. The cache: a second run makes no embed calls for unchanged chunks; after one note is edited, only that note's chunks are re-embedded. An interruption (the fake fails on call N) resumes from the cache.
4. A full `eval run` over the e2e fixture vault with the synthetic queries produces both `report.md` and `results.json`. The expected verdict is engineered through the fake topic maps.
5. A missing model fails preflight with `ollama pull`.
6. Privacy: no query text appears in `caplog.text` during a full run.

### 9.3 No e2e test

The harness has no UI, so there is no e2e test.

## 10. Docs and release

- **README:** an "Evaluating search" section covering:
  - the three commands;
  - a one-entry YAML example;
  - where the files live;
  - the win rule;
  - expected first-run time;
  - a note that the reports are private.
- **ADR-0006:** a note that the bake-off harness exists, with a link to this spec. The result is added after the owner's run.
- **`system-design.md` §9:** Phase 3 is delivered (harness). Phase 3b is listed as conditional on the verdict.
- **`.env.example`:** the four settings, commented out.
- **Release:** CI releases v0.6.0.

## 11. Risks

| Risk | Mitigation |
|---|---|
| 50 queries is a small sample, so noise could decide | A margin of 5 points, a paired bootstrap interval and the flip list are shown next to the verdict. The rule is fixed in advance. |
| Queries written while looking at notes flatter text matching | Results are split by `kind`. The owner is asked to include paraphrase queries written without the note open. |
| A first run takes a long time on CPU | A resumable cache, an ETA printed early, and the option to run on the GPU workstation through `SB_EMBED_URL`. |
| The scratch database could be pointed at real data | URL guards, a read-only transaction on dev, and a separate migrations table for the scratch-only schema. |
| Model drift between runs | Ollama digests are recorded in every report. |

## 12. Acceptance checklist

- [ ] The scratch migration and `eval-prepare` work, and the dev and test schemas are unchanged (`schema-check` passes).
- [ ] The §9 unit and integration tests pass, including privacy.
- [ ] `just check` is clean and the API client is unchanged.
- [ ] Docs are updated.
- [ ] Owner: writes `queries.yaml`, runs `just eval-check` and `just eval-run`, and reads the verdict.
- [ ] CI is green on Linux and macOS and releases v0.6.0.

# Phase 2a: Vault Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the owner's Obsidian vault into a durable, always-current PostgreSQL index: full-text searchable at once, with local bge-m3 vectors added in the background, and correct after crashes, outages and offline edits.

**Architecture:**
- **Files:** a `vault` package does all filesystem work: paths and exclusions, reading and normalizing, parsing, chunking, move pairing, the watcher, reconcile and observe.
- **Data:** a `knowledge` package does all database and job work: the store, indexing, embedding, the procrastinate job app and queue, and status queries.
- **Process:** one `ai-second-brain worker` process runs the procrastinate job worker, the file watcher and a reconcile timer.
- **Status:** the API exposes status endpoints and the web app gets a Sources screen.

**Tech Stack:**
- Backend: Python 3.12 (uv), procrastinate 3.10 (PsycopgConnector), watchfiles 1.3, PyYAML 6, psycopg 3 async, pgvector `halfvec` + HNSW, httpx2, FastAPI.
- Web: React 19 / TanStack Query / Vitest / Playwright.

**Spec:** [docs/superpowers/specs/2026-09-30-phase-2a-vault-ingestion-design.md](../specs/2026-09-30-phase-2a-vault-ingestion-design.md)

## Global Constraints

- **Jobs and logs carry no content:** job arguments are ids only (no note text, titles or paths). Log lines from ingestion carry ids, counts, durations, outcomes and error codes, and **never note text, titles or paths**. The `error` column and `metadata.embed_error` hold codes only.
- **Error codes (the complete set):** `too_large`, `encoding`, `io_error` (counted, not stored), `index_error`, `embed_unreachable`, `embed_model_missing`, `embed_bad_response`. Run outcomes: `ok`, `guard_tripped`, `vault_unavailable`, `disabled`, `error:<code>`.
- **Chunking:** at most 1600 characters per chunk; each continuation chunk starts with ≤ 200 characters of overlap from the previous chunk, snapped forward to a word boundary; heading-aware; `#` lines inside fenced code are never headings.
- **Embedding input:** `f"{title} › {' › '.join(heading_path)}\n\n{content}"`, with ` › …` left out when `heading_path` is empty. Default space id 1, model `bge-m3`, 1024 dimensions.
- **Mass-deletion guard:** it trips when the number to tombstone is `> 10` **and** `> 20%` of live sources. Only `ai-second-brain vault reconcile --allow-mass-delete` overrides it; the API never does.
- **Embedding transport:** `httpx2.AsyncClient(follow_redirects=False, trust_env=False)`, 5 s connect, 120 s read. There's no cloud fallback, ever.
- **No hosted Ollama models:** model names ending in `:cloud` or `-cloud` are rejected in settings (plan ruling 7).
- **Retries:**
  - `index_source`: 3 retries (10 s, 30 s, 90 s), then the revision is marked `failed` with `index_error`;
  - `embed_revision` on `embed_unreachable`: 8 retries (30, 60, 120, 300, 600, 1200, 2400, 3600 s);
  - `embed_model_missing` / `embed_bad_response`: no retry.
- **Settings:**
  - `SB_VAULT_PATH` (empty → ingestion disabled);
  - `SB_VAULT_EXCLUDE` (default `.obsidian/**,.trash/**,**/.git/**`);
  - `SB_EMBED_URL` (empty → the first `SB_OLLAMA_ENDPOINTS` URL);
  - `SB_EMBED_MODEL` (`bge-m3`);
  - `SB_EMBED_BATCH` (16, 1–128);
  - `SB_RECONCILE_MINUTES` (15, 1–1440);
  - `SB_MAX_NOTE_BYTES` (2 000 000, 1 000–50 000 000).
- **Exact UI copy** (Sources screen, spec §7.2):
  - "No vault configured. Set SB_VAULT_PATH to your Obsidian vault and restart the worker."
  - "The vault folder can't be read. Nothing was deleted."
  - "The last scan found {n} notes missing and deleted nothing. Check the vault path, then run `ai-second-brain vault reconcile --allow-mass-delete`."
  - "The embedding model isn't installed. Run `ollama pull {model}` on the embedding host."
  - "The embedding host is unreachable. Notes stay searchable by text; vectors are added when it's back."
  - Badges: "Waiting", "Searchable", "Text only", "Failed · {code}", "Deleted".
- **API:**
  - errors use the 1a format `{"detail": "<code>"}`; validation errors are `422 invalid_request`;
  - every endpoint requires a session; POSTs pass the same-origin guard.
- **Web:** token utilities only (no colour literals), TypeScript strict, Biome clean.
- **Commits:** Conventional Commits straight to `main`, **never** `Co-Authored-By` or any AI attribution. **Do NOT push** (owner decision: one push at the end of the phase). No manual tags.
- **Cross-platform:** everything runs on Windows (PowerShell), macOS and Linux. Async code runs on the selector loop (`ai_second_brain.runtime.new_event_loop`).

## Plan rulings (differences from the spec, decided while planning)

1. **Queueing after commit.** procrastinate queues jobs on its own connection, so a job can't be queued in the same transaction as the revision. Jobs are queued right after the data commits. If the process dies in between, reconcile's recovery step (spec §6.3 step 4) re-queues it. `AlreadyEnqueued` (queue-lock collision) is treated as success.
2. **Stuck-job detection uses worker heartbeats.** procrastinate 3 detects stalled jobs by worker heartbeat, not job age: `get_stalled_jobs(seconds_since_heartbeat=600)` followed by `retry_job`. The intent ("stuck for more than 10 minutes") is unchanged.
3. **The reconcile schedule is a timer inside the worker.** procrastinate's periodic cron is fixed when the code loads, and `SB_RECONCILE_MINUTES` can be up to 1440. So the interval is an asyncio loop in the worker process. Manual runs from the API are a procrastinate task, `reconcile_vault(run_id)`.
4. **Watcher batches use the same mass-deletion guard.** A batch that would tombstone more than 10 and more than 20% of live sources tombstones nothing and leaves the decision to reconcile. This is safer than the spec's reconcile-only guard.
5. **A move onto a path that already has a source** (even a tombstoned one) isn't paired. The new path is observed and the old one tombstoned, which avoids a unique-key conflict.
6. **A duplicate running job is allowed.** A queue lock only covers jobs still waiting. A job queued while another for the same id is running is harmless: `index_source` finds nothing pending, and embedding inserts use `ON CONFLICT DO NOTHING`.
7. **The model name is the Ollama tag; hosted models are refused.**
   - `SB_EMBED_MODEL` is the exact Ollama tag sent to `/api/embed`, for example `bge-m3:567m`. The owner's Ollama has `bge-m3:567m` and no `bge-m3:latest`, so plain `bge-m3` would get a 404.
   - The worker's startup check accepts the tag when it equals the default space's `model` (`bge-m3`) or starts with `bge-m3:`.
   - Model names ending in `:cloud` or `-cloud` (Ollama's hosted models, which forward to ollama.com) are **rejected** for both `SB_EMBED_MODEL` and every `SB_OLLAMA_ENDPOINTS` model. This enforces the routing spec's "never use hosted Ollama/model identifiers" for chat too.

## Review Focus

1. **Obsidian saves by writing a temp file and renaming it,** so a watcher batch can report "deleted" for a path that exists again. That path must be treated as modified, never tombstoned. Pinned in Task 9 (`test_apply_batch_deleted_but_present_is_observed`).
2. **Copying a note** (same content, second path, original still present) must create a second source, not be paired as a move. Pinned in Task 8 (`test_copy_is_not_a_move`).
3. **Polish characters, spaces and a case-only rename** in file names (`Notatki/Zażółć gęślą.md`, `Note.md` → `note.md` on a case-insensitive filesystem) must keep the source, and case-only renames pair as moves. Pinned in Task 3 (`test_rel_path_keeps_unicode_and_spaces`) and Task 5 (`test_case_only_rename_pairs`).
4. **An empty or whitespace-only note** is indexed with zero chunks, its embedding job completes without calling Ollama, and it shows as "Searchable". Pinned in Task 7 (`test_empty_note_indexes_with_zero_chunks`).
5. **A note edited while its embedding job waits** must make that job skip (stale revision) without calling Ollama. Pinned in Task 7 (`test_embed_skips_superseded_revision`).

---

## File map

**Backend (`backend/src/ai_second_brain/`)**

| File | Responsibility |
|---|---|
| `config.py` (modify) | Vault and embedding settings, the `http_url` validator shared with chat endpoints, and the `embed_url` property |
| `vault/__init__.py` | Package marker |
| `vault/paths.py` | `Vault` (root, exclusions, candidate test, relative/absolute paths, walk) |
| `vault/read.py` | `ReadNote`, `read_note`, `normalize_bytes` |
| `vault/parse.py` | `ParsedNote`, `parse_note`, `iter_outside_code` |
| `vault/chunk.py` | `Chunk`, `chunk_note` |
| `vault/moves.py` | `pair_moves`, `guard_trips` |
| `vault/observe.py` | `observe(ctx, rel)` |
| `vault/batch.py` | `apply_batch(ctx, changes)` (watcher batch → moves, observe, tombstone) |
| `vault/reconcile.py` | `reconcile(ctx, …)` and `ReconcileCounts` |
| `vault/watcher.py` | `run_watcher(vault, handle_batch, stop_event)` |
| `knowledge/__init__.py` | Package marker |
| `knowledge/context.py` | `IngestContext` (dependencies passed to jobs) |
| `knowledge/embed_text.py` | `embed_input` |
| `knowledge/embedder.py` | `Embedder`, `EmbedError` (the Ollama `/api/embed` client) |
| `knowledge/store.py` | Every SQL statement for sources, revisions, chunks, embeddings and runs |
| `knowledge/queue.py` | The `JobQueue` protocol and `ProcrastinateQueue` |
| `knowledge/jobs.py` | procrastinate `Blueprint`: `index_source`, `embed_revision`, `reconcile_vault`; retry strategies; `create_job_app` |
| `knowledge/index.py` | `index_source(ctx, source_id)` |
| `knowledge/embed.py` | `embed_revision(ctx, revision_id, space_id)` |
| `knowledge/status.py` | Summary and source-list queries for the API and CLI |
| `ingest/worker.py` | `run_worker(settings)`: the process (worker, watcher, timer, signals) |
| `interfaces/api/routes/sources.py`, `schemas.py` (modify), `app.py` (modify) | Sources API |
| `interfaces/cli/main.py` (modify) | `worker`, `vault reconcile`, `vault status` |

**Backend tests (`backend/tests/`)**

| File | Covers |
|---|---|
| `fakes/ollama.py` (modify) | Adds `/api/embed` |
| `fakes/queue.py` | `RecordingQueue` |
| `vaults.py` | `VaultBuilder` test helper |
| `ingest_harness.py` | `ingest_harness()`: pool, job app, context, drain, SQL helpers (integration) |
| `unit/test_vault_settings.py`, `unit/test_vault_paths.py`, `unit/test_vault_read.py`, `unit/test_vault_parse.py`, `unit/test_vault_chunk.py`, `unit/test_vault_moves.py`, `unit/test_embedder.py`, `unit/test_watcher.py` | Unit tests |
| `integration/test_procrastinate_schema.py`, `integration/test_ingest_index.py`, `integration/test_ingest_embed.py`, `integration/test_ingest_reconcile.py`, `integration/test_ingest_batch.py`, `integration/test_sources_api.py`, `unit/test_cli_vault.py` | Integration and CLI tests |

**Other:**
- `db/migrations/20260930100000_procrastinate.sql`, `db/migrations/20260930100100_knowledge.sql`, `db/schema.sql`
- the root `justfile` and `backend/justfile`, `.env.example`
- web: `src/features/sources/*`, `src/routes/_app/sources.tsx`, tokens
- e2e: `web/tests/e2e/fixtures/vault/*`, `fake-ollama.ts` (embed), `sources.spec.ts`, `playwright.config.ts`
- docs: README, ADR-0003, ADR-0006, `system-design.md` §9

---

### Task 1: Settings, dependencies and the Windows procrastinate smoke check

**Files:**
- Modify: `backend/pyproject.toml`, `backend/src/ai_second_brain/config.py`, `.env.example`
- Create: `backend/tests/unit/test_vault_settings.py`

**Interfaces:**
- Produces:
  - `http_url(value: str) -> str` (module-level validator: http/https, host, no user info, no `?`/`#`, trailing `/` stripped; raises `ValueError`), now also used by `OllamaEndpointConfig`;
  - new `Settings` fields `vault_path: Path | None`, `vault_exclude: str`, `embed_url_override: str` (env `SB_EMBED_URL`), `embed_model: str`, `embed_batch: int`, `reconcile_minutes: int`, `max_note_bytes: int`;
  - properties `vault_excludes -> tuple[str, ...]` and `embed_url -> str | None`.

- [ ] **Step 1: Add dependencies** (from `backend/`)

```bash
uv add "procrastinate[psycopg]>=3.10,<3.11" "watchfiles>=1.3" "pyyaml>=6.0"
uv add --dev "types-pyyaml"
```

- [ ] **Step 2: Windows smoke check of procrastinate (throwaway, not committed)**

This checks that procrastinate runs a job on this machine's selector event loop against the dev database *before* anything depends on it. Run from `backend/` against a scratch schema in the dev DB:

```bash
uv run python -c "
import asyncio, os
from procrastinate import App, PsycopgConnector
from procrastinate.schema import SchemaManager
from ai_second_brain.runtime import new_event_loop
url = os.environ['DATABASE_URL']
async def main():
    import psycopg
    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as c:
        await c.execute('DROP SCHEMA IF EXISTS pcsmoke CASCADE; CREATE SCHEMA pcsmoke')
    app = App(connector=PsycopgConnector(conninfo=url, kwargs={'options': '-c search_path=pcsmoke'}))
    done = []
    @app.task(name='ping')
    async def ping(x: int) -> None: done.append(x)
    async with app.open_async():
        await app.schema_manager.apply_schema_async()
        await ping.defer_async(x=7)
        await app.run_worker_async(wait=False, install_signal_handlers=False, listen_notify=False)
    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as c:
        await c.execute('DROP SCHEMA pcsmoke CASCADE')
    print('OK' if done == [7] else f'FAIL {done}')
asyncio.run(main(), loop_factory=new_event_loop)
"
```

Run it with `DATABASE_URL` set from `.env` (for example `just --dotenv-path ../.env` isn't needed; in PowerShell, `$env:DATABASE_URL = (Select-String -Path ../.env -Pattern '^DATABASE_URL=').Line.Split('=',2)[1]` first).
Expected: `OK`. If this fails on Windows, **stop and report BLOCKED** with the error: the fallback in spec §12 (a hand-rolled `SKIP LOCKED` queue) is an owner decision.

- [ ] **Step 3: Write the failing settings tests**

`backend/tests/unit/test_vault_settings.py`:

```python
from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_second_brain.config import OllamaEndpointConfig, Settings, http_url


def test_ingest_defaults(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings()
    assert settings.vault_path is None
    assert settings.vault_excludes == (".obsidian/**", ".trash/**", "**/.git/**")
    assert settings.embed_url is None
    assert settings.embed_model == "bge-m3"
    assert settings.embed_batch == 16
    assert settings.reconcile_minutes == 15
    assert settings.max_note_bytes == 2_000_000


def test_embed_url_falls_back_to_first_chat_endpoint(
    make_settings: Callable[..., Settings],
) -> None:
    endpoints = [
        {"label": "gpu", "url": "http://10.0.0.5:11434/", "model": "m"},
        {"label": "cpu", "url": "http://10.0.0.6:11434", "model": "m"},
    ]
    assert make_settings(ollama_endpoints=endpoints).embed_url == "http://10.0.0.5:11434"
    explicit = make_settings(ollama_endpoints=endpoints, embed_url_override="http://10.0.0.9:11434/")
    assert explicit.embed_url == "http://10.0.0.9:11434"


@pytest.mark.parametrize(
    "url", ["ftp://h", "http://", "http://u:p@h", "http://h/?x", "http://h#f", "h:11434"]
)
def test_embed_url_rules(make_settings: Callable[..., Settings], url: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(embed_url_override=url)


def test_http_url_is_shared_with_chat_endpoints() -> None:
    assert http_url(" http://h:1/ ") == "http://h:1"
    with pytest.raises(ValidationError):
        OllamaEndpointConfig(label="x", url="http://u:p@h", model="m")


def test_vault_path_must_be_absolute(make_settings: Callable[..., Settings], tmp_path: Path) -> None:
    assert make_settings(vault_path=str(tmp_path)).vault_path == tmp_path
    with pytest.raises(ValidationError):
        make_settings(vault_path="relative/vault")


def test_excludes_parse_and_trim(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(vault_exclude=" Archive/** , ,*.tmp.md ")
    assert settings.vault_excludes == ("Archive/**", "*.tmp.md")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("embed_batch", 0), ("embed_batch", 129),
        ("reconcile_minutes", 0), ("reconcile_minutes", 1441),
        ("max_note_bytes", 999), ("max_note_bytes", 50_000_001),
        ("embed_model", ""),
    ],
)
def test_bounds(make_settings: Callable[..., Settings], field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        make_settings(**{field: value})


def test_embed_url_env_alias(monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings]) -> None:
    monkeypatch.setenv("SB_EMBED_URL", "http://127.0.0.1:11434")
    assert make_settings().embed_url == "http://127.0.0.1:11434"


@pytest.mark.parametrize("model", ["kimi-k2.6:cloud", "qwen3-coder:480b-cloud", "GLM-5:CLOUD"])
def test_hosted_ollama_models_are_rejected(make_settings: Callable[..., Settings], model: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(embed_model=model)
    with pytest.raises(ValidationError):
        OllamaEndpointConfig(label="x", url="http://127.0.0.1:11434", model=model)


def test_tagged_local_models_are_fine(make_settings: Callable[..., Settings]) -> None:
    assert make_settings(embed_model="bge-m3:567m").embed_model == "bge-m3:567m"
    assert OllamaEndpointConfig(label="x", url="http://127.0.0.1:11434", model="gemma4:26b").model == "gemma4:26b"


def test_model_matches_space() -> None:
    from ai_second_brain.config import model_matches_space

    assert model_matches_space("bge-m3", "bge-m3")
    assert model_matches_space("bge-m3:567m", "bge-m3")
    assert not model_matches_space("bge-m3x", "bge-m3")
    assert not model_matches_space("nomic-embed-text", "bge-m3")
```

Run: `uv run pytest tests/unit/test_vault_settings.py -v`. Expected: FAIL (`ImportError: cannot import name 'http_url'`).

- [ ] **Step 4: Implement the settings**

In `config.py`:
- Add `http_url` above `OllamaEndpointConfig` and use it from `_check_url`:

```python
def http_url(value: str) -> str:
    """Validated http(s) origin/base URL: host required, no credentials, query or fragment."""
    value = value.strip()
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("must be an http:// or https:// URL with a host")
    if parts.username is not None or parts.password is not None:
        raise ValueError("must not contain a user name or password")
    if "?" in value or "#" in value:
        raise ValueError("must not contain a query string or fragment")
    return value.rstrip("/")
```

`OllamaEndpointConfig._check_url` becomes `return http_url(value)`.

Add two more module-level helpers next to `http_url`, and use the first one as a validator on `OllamaEndpointConfig.model` (`@field_validator("model")`) and on `Settings.embed_model`:

```python
HOSTED_MODEL_SUFFIXES = (":cloud", "-cloud")


def local_model_name(value: str) -> str:
    """Reject Ollama's hosted models: they forward prompts to ollama.com."""
    value = value.strip()
    if value.lower().endswith(HOSTED_MODEL_SUFFIXES):
        raise ValueError("hosted (cloud) Ollama models are not allowed; use a local model")
    return value


def model_matches_space(tag: str, space_model: str) -> bool:
    """An Ollama tag like 'bge-m3:567m' belongs to the embedding space 'bge-m3'."""
    return tag == space_model or tag.startswith(f"{space_model}:")
```
- Add `from pathlib import Path` (already imported) and these `Settings` fields after `chat_status_ttl_seconds`:

```python
    vault_path: Path | None = None
    vault_exclude: str = ".obsidian/**,.trash/**,**/.git/**"
    embed_url_override: str = Field(default="", validation_alias="SB_EMBED_URL")
    embed_model: str = Field(default="bge-m3", min_length=1)
    embed_batch: int = Field(default=16, ge=1, le=128)
    reconcile_minutes: int = Field(default=15, ge=1, le=1440)
    max_note_bytes: int = Field(default=2_000_000, ge=1_000, le=50_000_000)

    @field_validator("vault_path")
    @classmethod
    def _absolute_vault(cls, value: Path | None) -> Path | None:
        if value is not None and not value.is_absolute():
            raise ValueError("SB_VAULT_PATH must be an absolute path")
        return value

    @field_validator("embed_url_override")
    @classmethod
    def _embed_url(cls, value: str) -> str:
        return http_url(value) if value.strip() else ""

    @field_validator("embed_model")
    @classmethod
    def _local_embed_model(cls, value: str) -> str:
        return local_model_name(value)

    @property
    def vault_excludes(self) -> tuple[str, ...]:
        return tuple(p.strip() for p in self.vault_exclude.split(",") if p.strip())

    @property
    def embed_url(self) -> str | None:
        if self.embed_url_override:
            return self.embed_url_override
        return self.ollama_endpoints[0].url if self.ollama_endpoints else None
```

`populate_by_name=True` is already set, so tests may pass `embed_url_override=`. The environment variable is `SB_EMBED_URL` through the alias.

Append to `.env.example`:

```dotenv

# Vault ingestion (Phase 2a). Absolute path; empty = ingestion disabled.
# SB_VAULT_PATH=C:\Users\me\Documents\Obsidian\Vault
# Comma-separated glob patterns (vault-relative, forward slashes) to skip. Only *.md is read.
# SB_VAULT_EXCLUDE=.obsidian/**,.trash/**,**/.git/**
# Embedding host (Ollama). Empty = the first SB_OLLAMA_ENDPOINTS URL. Run `ollama pull bge-m3` there.
# Prefer 127.0.0.1 over localhost on Windows (localhost tries IPv6 first and can stall).
# SB_EMBED_URL=http://127.0.0.1:11434
# Exact Ollama tag (see `ollama list`), e.g. bge-m3:567m. Hosted ":cloud" models are refused.
# SB_EMBED_MODEL=bge-m3
# SB_EMBED_BATCH=16
# SB_RECONCILE_MINUTES=15
# SB_MAX_NOTE_BYTES=2000000
```

- [ ] **Step 5: Verify**

Run: `uv run pytest -m "not integration" -q`. Expected: all pass (the existing config tests are unchanged).
Run: `just backend::check`. Expected: clean.

- [ ] **Step 6: Commit (no push)**

```bash
git add backend/pyproject.toml backend/uv.lock backend/src/ai_second_brain/config.py backend/tests/unit/test_vault_settings.py .env.example
git commit -m "feat(ingest): add vault and embedding settings"
```

---

### Task 2: Migrations, the procrastinate job app and schema pinning

**Files:**
- Create:
  - `db/migrations/20260930100000_procrastinate.sql`, `db/migrations/20260930100100_knowledge.sql`
  - `backend/src/ai_second_brain/knowledge/__init__.py`, `backend/src/ai_second_brain/knowledge/jobs.py`
  - `backend/tests/integration/test_procrastinate_schema.py`
- Modify: `db/schema.sql` (regenerated)

**Interfaces:**
- Produces:
  - the tables in spec §4.1 (verbatim), plus procrastinate's schema;
  - `knowledge.jobs.blueprint: procrastinate.Blueprint`;
  - `knowledge.jobs.create_job_app(database_url: str) -> procrastinate.App` (tasks registered under namespace `ingest`, so task names are `ingest:index_source`, `ingest:embed_revision`, `ingest:reconcile_vault`);
  - the constants `INGEST_QUEUE = "ingest"`, `EMBED_QUEUE = "embed"`.
- Task bodies are filled in by Tasks 6–8. This task registers them with bodies that raise `NotImplementedError`.

- [ ] **Step 1: Vendor procrastinate's schema** (from the repo root)

```bash
uv run --directory backend python -c "from procrastinate.schema import SchemaManager; import sys; sys.stdout.write(SchemaManager.get_schema())" > procrastinate_schema.tmp.sql
```

Create `db/migrations/20260930100000_procrastinate.sql` as:

```sql
-- migrate:up
-- Vendored verbatim from procrastinate 3.10 (procrastinate.schema.SchemaManager.get_schema()).
-- Upgrading procrastinate = a new migration with its published migration SQL. Never edit this block.
<the full contents of procrastinate_schema.tmp.sql>

-- migrate:down
DROP TABLE IF EXISTS procrastinate_events, procrastinate_periodic_defers, procrastinate_jobs, procrastinate_workers CASCADE;
DO $$
DECLARE r record;
BEGIN
  FOR r IN SELECT p.oid::regprocedure AS sig FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
           WHERE n.nspname = 'public' AND p.proname LIKE 'procrastinate\_%' LOOP
    EXECUTE 'DROP FUNCTION IF EXISTS ' || r.sig || ' CASCADE';
  END LOOP;
  FOR r IN SELECT t.typname FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
           WHERE n.nspname = 'public' AND t.typname LIKE 'procrastinate\_%' AND t.typtype IN ('e', 'c') LOOP
    EXECUTE 'DROP TYPE IF EXISTS ' || quote_ident(r.typname) || ' CASCADE';
  END LOOP;
END $$;
```

Then delete `procrastinate_schema.tmp.sql`. The first line of the up section after the two comment lines must be the schema text exactly. If the schema defines tables not named in the `DROP TABLE` line, add them there.

- [ ] **Step 2: Write the knowledge migration**

Create `db/migrations/20260930100100_knowledge.sql` with **exactly** the SQL of spec §4.1 (the up section and the down section as written there).

- [ ] **Step 3: Apply, roll back, re-apply** (from the repo root)

```bash
just db::migrate
just db::rollback
just db::rollback
just db::migrate
just db::test-prepare
just db::dump
```

Expected: every command succeeds, and `db/schema.sql` contains `procrastinate_jobs`, `sources`, `chunk_embeddings` and `chunk_emb_s1_hnsw`.

- [ ] **Step 4: Write the job app with placeholder task bodies**

`backend/src/ai_second_brain/knowledge/__init__.py`: `"""Indexed knowledge: store, jobs, indexing, embedding."""`

`backend/src/ai_second_brain/knowledge/jobs.py`:

```python
"""procrastinate job app. Job arguments are ids only; never note text, titles or paths."""

from procrastinate import App, Blueprint, JobContext, PsycopgConnector

INGEST_QUEUE = "ingest"
EMBED_QUEUE = "embed"

blueprint = Blueprint()


@blueprint.task(name="index_source", queue=INGEST_QUEUE, pass_context=True)
async def index_source_task(context: JobContext, source_id: str) -> None:
    raise NotImplementedError  # Task 6


@blueprint.task(name="embed_revision", queue=EMBED_QUEUE, pass_context=True)
async def embed_revision_task(context: JobContext, revision_id: str, space_id: int) -> None:
    raise NotImplementedError  # Task 7


@blueprint.task(name="reconcile_vault", queue=INGEST_QUEUE, pass_context=True)
async def reconcile_vault_task(context: JobContext, run_id: int) -> None:
    raise NotImplementedError  # Task 8


def create_job_app(database_url: str) -> App:
    app = App(connector=PsycopgConnector(conninfo=database_url))
    app.add_tasks_from(blueprint, namespace="ingest")
    return app
```

(The three `NotImplementedError` bodies are deliberate scaffolding; Tasks 6, 7 and 8 replace each one.)

- [ ] **Step 5: Write the schema-pinning test**

`backend/tests/integration/test_procrastinate_schema.py`:

```python
from pathlib import Path

import pytest
from procrastinate.schema import SchemaManager

from ai_second_brain.config import REPO_ROOT
from ai_second_brain.knowledge.jobs import create_job_app

from ..conftest import run_async

pytestmark = pytest.mark.integration

MIGRATION = REPO_ROOT / "db" / "migrations" / "20260930100000_procrastinate.sql"


def vendored_up_sql(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    up = text.split("-- migrate:up", 1)[1].split("-- migrate:down", 1)[0]
    lines = up.splitlines()
    body = [line for line in lines if not line.startswith("-- Vendored") and not line.startswith("-- Upgrading")]
    return "\n".join(body).strip()


def test_vendored_schema_matches_installed_procrastinate() -> None:
    assert vendored_up_sql(MIGRATION) == SchemaManager.get_schema().strip()


def test_job_app_registers_ingest_tasks(db_url: str) -> None:
    app = create_job_app(db_url)
    assert {"ingest:index_source", "ingest:embed_revision", "ingest:reconcile_vault"} <= set(app.tasks)

    async def scenario() -> None:
        async with app.open_async():
            assert await app.check_connection_async()

    run_async(scenario())
```

- [ ] **Step 6: Verify**

Run: `just backend::test tests/integration/test_procrastinate_schema.py -v`. Expected: 2 passed.
Run: `just check`. Expected: clean (the schema check passes after `just db::dump`).

- [ ] **Step 7: Commit (no push)**

```bash
git add db/migrations db/schema.sql backend/src/ai_second_brain/knowledge backend/tests/integration/test_procrastinate_schema.py
git commit -m "feat(ingest): add knowledge schema and job queue"
```

---

### Task 3: Vault paths, reading and parsing

**Files:**
- Create:
  - `backend/src/ai_second_brain/vault/__init__.py`, `vault/paths.py`, `vault/read.py`, `vault/parse.py`
  - `backend/tests/vaults.py`
  - `backend/tests/unit/test_vault_paths.py`, `test_vault_read.py`, `test_vault_parse.py`

**Interfaces:**
- Produces:
  - `Vault(root: Path, excludes: tuple[str, ...])` with `.is_candidate(rel) -> bool`, `.rel(path: Path) -> str | None`, `.abs(rel) -> Path`, `.walk() -> dict[str, tuple[int, int]]` (rel → (size, mtime_ns)), `.readable() -> bool`;
  - `ReadNote(text, content_hash, size, mtime_ns, error)`, `read_note(path, max_bytes) -> ReadNote` (raises `OSError` for I/O errors), `normalize_bytes(data) -> tuple[str, bytes]` (raises `UnicodeDecodeError`);
  - `ParsedNote(title, body, frontmatter, frontmatter_error, links)`, `parse_note(text, stem) -> ParsedNote`, `iter_outside_code(lines) -> Iterator[tuple[str, bool]]` (each line with a flag saying whether it's inside a fenced block);
  - test helper `VaultBuilder(root)` with `.write(rel, text | bytes) -> Path`, `.delete(rel)`, `.rename(old, new)`.

- [ ] **Step 1: Write the test helper**

`backend/tests/vaults.py`:

```python
"""Build throwaway vaults in tmp_path."""

import os
from pathlib import Path


class VaultBuilder:
    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def write(self, rel: str, content: str | bytes, *, mtime_ns: int | None = None) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8", newline="")
        if mtime_ns is not None:
            os.utime(path, ns=(mtime_ns, mtime_ns))
        return path

    def delete(self, rel: str) -> None:
        (self.root / rel).unlink()

    def rename(self, old: str, new: str) -> None:
        target = self.root / new
        target.parent.mkdir(parents=True, exist_ok=True)
        (self.root / old).rename(target)
```

- [ ] **Step 2: Write the failing tests**

`backend/tests/unit/test_vault_paths.py`:

```python
from pathlib import Path

from ai_second_brain.vault.paths import Vault

from ..vaults import VaultBuilder

EXCLUDES = (".obsidian/**", ".trash/**", "**/.git/**")


def test_candidates_are_markdown_outside_excludes(tmp_path: Path) -> None:
    vault = Vault(tmp_path, EXCLUDES)
    assert vault.is_candidate("Notes/a.md")
    assert vault.is_candidate("Notes/A.MD")
    assert not vault.is_candidate("Notes/a.txt")
    assert not vault.is_candidate(".obsidian/workspace.md")
    assert not vault.is_candidate(".trash/old.md")
    assert not vault.is_candidate(".git/x.md")
    assert not vault.is_candidate("Projects/.git/x.md")


def test_rel_path_keeps_unicode_and_spaces(tmp_path: Path) -> None:
    vault = Vault(tmp_path, EXCLUDES)
    path = tmp_path / "Notatki" / "Zażółć gęślą.md"
    assert vault.rel(path) == "Notatki/Zażółć gęślą.md"
    assert vault.abs("Notatki/Zażółć gęślą.md") == path
    assert vault.rel(tmp_path.parent / "outside.md") is None


def test_walk_lists_candidates_with_size_and_mtime(tmp_path: Path) -> None:
    builder = VaultBuilder(tmp_path)
    builder.write("a.md", "alpha", mtime_ns=1_700_000_000_000_000_000)
    builder.write("Sub/b.md", "bravo!")
    builder.write(".obsidian/c.md", "x")
    builder.write("Sub/d.txt", "x")
    walked = Vault(tmp_path, EXCLUDES).walk()
    assert set(walked) == {"a.md", "Sub/b.md"}
    assert walked["a.md"] == (5, 1_700_000_000_000_000_000)
    assert walked["Sub/b.md"][0] == 6


def test_readable(tmp_path: Path) -> None:
    assert Vault(tmp_path, EXCLUDES).readable()
    assert not Vault(tmp_path / "missing", EXCLUDES).readable()
```

`backend/tests/unit/test_vault_read.py`:

```python
import hashlib
import unicodedata
from pathlib import Path

from ai_second_brain.vault.read import normalize_bytes, read_note

POLISH = "Zażółć gęślą jaźń"


def test_nfc_nfd_bom_and_newlines_hash_equally() -> None:
    nfc = unicodedata.normalize("NFC", POLISH) + "\r\nline"
    nfd = unicodedata.normalize("NFD", POLISH) + "\nline"
    a = normalize_bytes(nfc.encode())
    b = normalize_bytes(b"\xef\xbb\xbf" + nfd.encode())
    c = normalize_bytes((unicodedata.normalize("NFC", POLISH) + "\rline").encode())
    assert a == b == c
    assert a[0] == unicodedata.normalize("NFC", POLISH) + "\nline"
    assert a[1] == hashlib.sha256(a[0].encode()).digest()


def test_read_note_ok(tmp_path: Path) -> None:
    path = tmp_path / "n.md"
    path.write_bytes("héllo".encode())
    note = read_note(path, max_bytes=1000)
    assert note.error is None
    assert note.text == "héllo"
    assert note.size == len("héllo".encode())
    assert note.mtime_ns == path.stat().st_mtime_ns


def test_invalid_utf8_is_encoding_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.md"
    path.write_bytes(b"\xff\xfe\x00bad")
    note = read_note(path, max_bytes=1000)
    assert (note.error, note.text) == ("encoding", "")
    assert note.content_hash == hashlib.sha256(b"\xff\xfe\x00bad").digest()


def test_too_large_is_never_read(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "big.md"
    path.write_bytes(b"x" * 2000)

    def refuse(*args: object, **kwargs: object) -> bytes:
        raise AssertionError("oversized file must not be read")

    monkeypatch.setattr(Path, "read_bytes", refuse)
    note = read_note(path, max_bytes=1000)
    st = path.stat()
    assert (note.error, note.text, note.size) == ("too_large", "", 2000)
    assert note.content_hash == hashlib.sha256(f"too_large:2000:{st.st_mtime_ns}".encode()).digest()
```

`backend/tests/unit/test_vault_parse.py`:

```python
from ai_second_brain.vault.parse import parse_note


def test_title_prefers_frontmatter_then_h1_then_stem() -> None:
    assert parse_note("---\ntitle: From FM\n---\n# H1\nbody", "file").title == "From FM"
    assert parse_note("intro\n# The H1 #\nbody", "file").title == "The H1"
    assert parse_note("```\n# not a title\n```\ntext", "file").title == "file"
    assert parse_note("---\ntitle: '  '\n---\nx", "stem").title == "stem"


def test_frontmatter_is_json_safe_and_removed_from_body() -> None:
    parsed = parse_note("---\ntags: [a, b]\ndate: 2026-09-30\n---\nBody here", "f")
    assert parsed.frontmatter == {"tags": ["a", "b"], "date": "2026-09-30"}
    assert parsed.frontmatter_error is False
    assert parsed.body == "Body here"


def test_invalid_or_non_dict_frontmatter_stays_in_body() -> None:
    broken = parse_note("---\nkey: [unclosed\n---\nBody", "f")
    assert broken.frontmatter is None and broken.frontmatter_error is True
    assert broken.body.startswith("---\nkey: [unclosed")
    listy = parse_note("---\n- a\n- b\n---\nBody", "f")
    assert listy.frontmatter is None and listy.frontmatter_error is True


def test_wikilinks_outside_code_deduplicated() -> None:
    text = (
        "See [[NAS]] and [[Backups|the backups]] and [[NAS#Disks]].\n"
        "`[[inline code]]`\n"
        "```\n[[in fence]]\n```\n"
    )
    assert parse_note(text, "f").links == ["NAS", "Backups"]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_vault_paths.py tests/unit/test_vault_read.py tests/unit/test_vault_parse.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ai_second_brain.vault'`.

- [ ] **Step 4: Implement**

`backend/src/ai_second_brain/vault/__init__.py`: `"""Filesystem side of ingestion: the Obsidian vault."""`

`backend/src/ai_second_brain/vault/paths.py`:

```python
"""Vault root, exclusions and candidate files (vault-relative POSIX paths)."""

import os
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath


def _excluded(rel: str, patterns: tuple[str, ...]) -> bool:
    for pattern in patterns:
        if fnmatchcase(rel, pattern):
            return True
        if pattern.startswith("**/") and fnmatchcase(rel, pattern[3:]):
            return True
    return False


@dataclass(frozen=True)
class Vault:
    root: Path
    excludes: tuple[str, ...]

    def is_candidate(self, rel: str) -> bool:
        return rel.lower().endswith(".md") and not _excluded(rel, self.excludes)

    def rel(self, path: Path) -> str | None:
        try:
            relative = path.resolve().relative_to(self.root.resolve())
        except ValueError:
            return None
        return PurePosixPath(*relative.parts).as_posix()

    def abs(self, rel: str) -> Path:
        return self.root.joinpath(*PurePosixPath(rel).parts)

    def readable(self) -> bool:
        return self.root.is_dir() and os.access(self.root, os.R_OK | os.X_OK)

    def walk(self) -> dict[str, tuple[int, int]]:
        found: dict[str, tuple[int, int]] = {}
        for dirpath, dirnames, filenames in os.walk(self.root, followlinks=False):
            base = Path(dirpath)
            rel_dir = PurePosixPath(*base.relative_to(self.root).parts).as_posix()
            prefix = "" if rel_dir == "." else f"{rel_dir}/"
            dirnames[:] = [d for d in dirnames if not _excluded(f"{prefix}{d}/", self.excludes)]
            for name in filenames:
                rel = f"{prefix}{name}"
                if not self.is_candidate(rel):
                    continue
                path = base / name
                if path.is_symlink():
                    continue
                st = path.stat()
                found[rel] = (st.st_size, st.st_mtime_ns)
        return found
```

`backend/src/ai_second_brain/vault/read.py`:

```python
"""Read and normalize one note. Never logs content."""

import hashlib
import unicodedata
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ReadNote:
    text: str  # '' when error is set
    content_hash: bytes
    size: int
    mtime_ns: int
    error: str | None  # 'too_large' | 'encoding' | None


def normalize_bytes(data: bytes) -> tuple[str, bytes]:
    text = data.decode("utf-8")  # raises UnicodeDecodeError
    text = text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    text = unicodedata.normalize("NFC", text)
    return text, hashlib.sha256(text.encode("utf-8")).digest()


def read_note(path: Path, max_bytes: int) -> ReadNote:
    """Raises OSError on I/O failure (the caller maps it to io_error)."""
    st = path.stat()
    if st.st_size > max_bytes:
        marker = f"too_large:{st.st_size}:{st.st_mtime_ns}".encode()
        return ReadNote("", hashlib.sha256(marker).digest(), st.st_size, st.st_mtime_ns, "too_large")
    data = path.read_bytes()
    try:
        text, digest = normalize_bytes(data)
    except UnicodeDecodeError:
        return ReadNote("", hashlib.sha256(data).digest(), st.st_size, st.st_mtime_ns, "encoding")
    return ReadNote(text, digest, st.st_size, st.st_mtime_ns, None)
```

`backend/src/ai_second_brain/vault/parse.py`:

```python
"""Obsidian note parsing: frontmatter, title, wikilinks. Pure and total."""

import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

import yaml

FRONTMATTER = re.compile(r"\A---\n(.*?)\n---[ \t]*(?:\n|\Z)", re.DOTALL)
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
H1 = re.compile(r"^#[ \t]+(.+?)[ \t#]*$")
INLINE_CODE = re.compile(r"`[^`\n]*`")
WIKILINK = re.compile(r"\[\[([^\]\|#\n]+)(?:#[^\]\|\n]*)?(?:\|[^\]\n]*)?\]\]")


@dataclass(frozen=True)
class ParsedNote:
    title: str
    body: str
    frontmatter: dict[str, Any] | None
    frontmatter_error: bool
    links: list[str] = field(default_factory=list)


def iter_outside_code(lines: Iterable[str]) -> Iterator[tuple[str, bool]]:
    """Yield (line, in_code). Fence open/close lines count as in_code."""
    fence: str | None = None
    for line in lines:
        match = FENCE.match(line)
        if fence is None and match:
            fence = match.group(1)[0] * len(match.group(1))
            yield line, True
        elif fence is not None:
            if match and match.group(1)[0] == fence[0] and len(match.group(1)) >= len(fence):
                fence = None
            yield line, True
        else:
            yield line, False


def _frontmatter(text: str) -> tuple[dict[str, Any] | None, bool, str]:
    match = FRONTMATTER.match(text)
    if not match:
        return None, False, text
    try:
        loaded = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None, True, text
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        return None, True, text
    safe = json.loads(json.dumps(loaded, default=str))
    return safe, False, text[match.end() :]


def parse_note(text: str, stem: str) -> ParsedNote:
    frontmatter, error, body = _frontmatter(text)
    title = None
    if frontmatter and isinstance(frontmatter.get("title"), str) and frontmatter["title"].strip():
        title = frontmatter["title"].strip()
    links: list[str] = []
    for line, in_code in iter_outside_code(body.split("\n")):
        if in_code:
            continue
        if title is None and (h1 := H1.match(line)):
            title = h1.group(1).strip()
        for target in WIKILINK.findall(INLINE_CODE.sub("", line)):
            target = target.strip()
            if target and target not in links:
                links.append(target)
    return ParsedNote(title or stem, body, frontmatter, error, links)
```

- [ ] **Step 5: Verify and commit (no push)**

Run: `uv run pytest tests/unit/test_vault_paths.py tests/unit/test_vault_read.py tests/unit/test_vault_parse.py -v` and `just backend::check`. Expected: all pass, clean.

```bash
git add backend/src/ai_second_brain/vault backend/tests/vaults.py backend/tests/unit/test_vault_paths.py backend/tests/unit/test_vault_read.py backend/tests/unit/test_vault_parse.py
git commit -m "feat(ingest): read and parse vault notes"
```

---

### Task 4: Heading-aware chunker

**Files:**
- Create: `backend/src/ai_second_brain/vault/chunk.py`, `backend/tests/unit/test_vault_chunk.py`

**Interfaces:**
- Consumes: `iter_outside_code` (Task 3).
- Produces: `MAX_CHARS = 1600`, `OVERLAP = 200`, `Chunk(ordinal: int, heading_path: tuple[str, ...], content: str)`, `chunk_note(body: str) -> list[Chunk]`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/unit/test_vault_chunk.py`:

```python
from ai_second_brain.vault.chunk import MAX_CHARS, OVERLAP, chunk_note


def words(n: int, word: str = "słowo") -> str:
    return " ".join([word] * n)


def test_heading_paths_and_fences() -> None:
    body = (
        "intro text\n"
        "# Projects\n"
        "top\n"
        "## NAS\n"
        "disks\n"
        "```bash\n# not a heading\n```\n"
        "### Deep\n"
        "deep\n"
        "## Backups\n"
        "nightly\n"
    )
    chunks = chunk_note(body)
    assert [(c.heading_path, c.content) for c in chunks] == [
        ((), "intro text"),
        (("Projects",), "top"),
        (("Projects", "NAS"), "disks\n```bash\n# not a heading\n```"),
        (("Projects", "NAS", "Deep"), "deep"),
        (("Projects", "Backups"), "nightly"),
    ]
    assert [c.ordinal for c in chunks] == [0, 1, 2, 3, 4]


def test_empty_sections_dropped_and_headingless_note() -> None:
    assert [c.content for c in chunk_note("# Empty\n\n# Full\ntext\n")] == ["text"]
    assert chunk_note("") == []
    assert chunk_note("  \n\n ") == []
    assert [c.heading_path for c in chunk_note("just text\n\nmore")] == [()]


def test_boundary_1600_is_one_chunk_1601_splits() -> None:
    exact = "a" * MAX_CHARS
    assert [c.content for c in chunk_note(exact)] == [exact]
    over = words(400)  # well over 1600 chars, no paragraph breaks
    chunks = chunk_note(over)
    assert len(chunks) > 1
    assert all(len(c.content) <= MAX_CHARS for c in chunks)


def test_paragraph_packing_and_overlap() -> None:
    paragraphs = [f"Paragraf {i}. " + words(40) for i in range(12)]
    chunks = chunk_note("\n\n".join(paragraphs))
    assert len(chunks) >= 3
    for previous, current in zip(chunks, chunks[1:], strict=False):
        assert len(current.content) <= MAX_CHARS
        # The chunk starts with a non-empty suffix (≤ OVERLAP chars) of the previous chunk.
        overlaps = [k for k in range(1, OVERLAP + 1) if current.content.startswith(previous.content[-k:])]
        assert overlaps, "continuation chunk must start with the tail of the previous chunk"
        assert max(overlaps) >= 20
        assert not current.content.startswith(" ")


def test_long_sentence_is_hard_split() -> None:
    chunks = chunk_note("x" * 5000)
    assert all(len(c.content) <= MAX_CHARS for c in chunks)
    assert "".join(c.content.replace("\n\n", "") for c in chunks).count("x") >= 5000
```

Run: `uv run pytest tests/unit/test_vault_chunk.py -v`. Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 2: Implement**

`backend/src/ai_second_brain/vault/chunk.py`:

```python
"""Heading-aware chunking. Chunks are ≤ MAX_CHARS; continuation chunks start with overlap."""

import re
from dataclasses import dataclass

from ai_second_brain.vault.parse import iter_outside_code

MAX_CHARS = 1600
OVERLAP = 200
UNIT_MAX = MAX_CHARS - OVERLAP - 2  # a unit always fits after an overlap + "\n\n"

HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)[ \t#]*$")
PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    heading_path: tuple[str, ...]
    content: str


def _sections(body: str) -> list[tuple[tuple[str, ...], str]]:
    sections: list[tuple[tuple[str, ...], list[str]]] = [((), [])]
    stack: list[tuple[int, str]] = []
    for line, in_code in iter_outside_code(body.split("\n")):
        match = None if in_code else HEADING.match(line)
        if match:
            level = len(match.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, match.group(2).strip()))
            sections.append((tuple(text for _, text in stack), []))
        else:
            sections[-1][1].append(line)
    return [(path, "\n".join(lines).strip()) for path, lines in sections]


def _units(text: str) -> list[tuple[str, str]]:
    """(joiner, unit) pairs; joiner is used before the unit inside a chunk."""
    units: list[tuple[str, str]] = []
    for paragraph in (p.strip() for p in PARAGRAPH_BREAK.split(text)):
        if not paragraph:
            continue
        if len(paragraph) <= UNIT_MAX:
            units.append(("\n\n", paragraph))
            continue
        first = True
        for sentence in (s for s in SENTENCE_END.split(paragraph) if s):
            pieces = [sentence[i : i + UNIT_MAX] for i in range(0, len(sentence), UNIT_MAX)]
            for piece in pieces:
                units.append(("\n\n" if first else " ", piece))
                first = False
    return units


def _overlap(previous: str) -> str:
    if len(previous) <= OVERLAP:
        return previous.strip()
    tail = previous[-OVERLAP:]
    space = next((i for i, ch in enumerate(tail) if ch.isspace()), -1)
    snapped = tail[space + 1 :].lstrip() if space != -1 else tail
    return snapped or tail.strip()


def _split(text: str) -> list[str]:
    if len(text) <= MAX_CHARS:
        return [text]
    chunks: list[str] = []
    current = ""
    for joiner, unit in _units(text):
        if not current:
            current = unit
        elif len(current) + len(joiner) + len(unit) <= MAX_CHARS:
            current = f"{current}{joiner}{unit}"
        else:
            chunks.append(current)
            current = f"{_overlap(current)}\n\n{unit}"
    if current:
        chunks.append(current)
    return chunks


def chunk_note(body: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path, text in _sections(body):
        if not text:
            continue
        for content in _split(text):
            chunks.append(Chunk(len(chunks), path, content))
    return chunks
```

- [ ] **Step 3: Verify and commit (no push)**

Run: `uv run pytest tests/unit/test_vault_chunk.py -v` and `just backend::check`. Expected: pass, clean. If a test shows a real off-by-one against the spec (a chunk over 1600 characters, overlap over 200), fix the code, never the limits.

```bash
git add backend/src/ai_second_brain/vault/chunk.py backend/tests/unit/test_vault_chunk.py
git commit -m "feat(ingest): chunk notes by heading"
```

---

### Task 5: Move pairing, the guard, embedding input and the embedding client

**Files:**
- Create:
  - `backend/src/ai_second_brain/vault/moves.py`, `backend/src/ai_second_brain/knowledge/embed_text.py`, `backend/src/ai_second_brain/knowledge/embedder.py`
  - `backend/tests/unit/test_vault_moves.py`, `backend/tests/unit/test_embedder.py`
- Modify: `backend/tests/fakes/ollama.py` (the `/api/embed` route)

**Interfaces:**
- Produces:
  - `pair_moves(deleted: Mapping[str, bytes], added: Mapping[str, bytes]) -> tuple[list[tuple[str, str]], list[str], list[str]]` returning (pairs of old→new, unpaired deleted, unpaired added), all sorted;
  - `guard_trips(to_tombstone: int, live: int) -> bool`;
  - `embed_input(title: str, heading_path: Sequence[str], content: str) -> str`;
  - `EmbedError(code)` with codes `embed_unreachable` | `embed_model_missing` | `embed_bad_response`, and `EmbedRetryable(Exception)` (raised by the Task 7 job; defined here to avoid an import cycle);
  - `Embedder(url: str, model: str, dims: int, client: httpx2.AsyncClient, timeouts: ChatTimeouts)` with `async embed(texts) -> list[list[float]]` and `async reachable() -> bool`;
  - on `FakeOllama.behaviour`: `embed_status` (200), `embed_error_text` (""), `embed_dims` (1024), `embed_count_delta` (0), `embed_nonfinite` (False), `embed_fail_on_call` (None, 1-based), `embed_delay` (0.0); plus `FakeOllama.embed_requests()` and `fake_vector(text, dims)`.

- [ ] **Step 1: Extend the fake Ollama**

In `backend/tests/fakes/ollama.py`:
- Add the fields to `OllamaBehaviour`:

```python
    embed_status: int = 200
    embed_error_text: str = ""
    embed_dims: int = 1024
    embed_count_delta: int = 0
    embed_nonfinite: bool = False
    embed_fail_on_call: int | None = None  # 1-based call number that returns 500
    embed_delay: float = 0.0
```

- Add a module-level function and a route (`Route("/api/embed", self._embed, methods=["POST"])` before the catch-all), plus the methods:

```python
def fake_vector(text: str, dims: int = 1024) -> list[float]:
    seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
    rng = random.Random(seed)
    values = [rng.gauss(0.0, 1.0) for _ in range(dims)]
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]
```

```python
    def embed_requests(self) -> list[RecordedRequest]:
        return [r for r in self.requests if r.path == "/api/embed"]

    async def _embed(self, request: Request) -> Response:
        body = await self._record(request)
        b = self.behaviour
        if b.embed_delay:
            await asyncio.sleep(b.embed_delay)
        if b.embed_fail_on_call is not None and len(self.embed_requests()) == b.embed_fail_on_call:
            return JSONResponse({"error": "boom"}, status_code=500)
        if b.embed_status != 200:
            return JSONResponse({"error": b.embed_error_text}, status_code=b.embed_status)
        inputs = body["input"] if isinstance(body["input"], list) else [body["input"]]
        vectors = [fake_vector(text, b.embed_dims) for text in inputs]
        if b.embed_count_delta < 0:
            vectors = vectors[: b.embed_count_delta]
        elif b.embed_count_delta > 0:
            vectors += [fake_vector("extra", b.embed_dims)] * b.embed_count_delta
        if b.embed_nonfinite and vectors:
            vectors[0] = [float("nan")] * b.embed_dims
        return JSONResponse({"model": body["model"], "embeddings": vectors})
```

(Add `import hashlib, math, random` at the top.) The embedding requests are then the recorded requests whose path is `/api/embed`.

- [ ] **Step 2: Write the failing tests**

`backend/tests/unit/test_vault_moves.py`:

```python
from ai_second_brain.knowledge.embed_text import embed_input
from ai_second_brain.vault.moves import guard_trips, pair_moves

H1, H2, H3 = b"1" * 32, b"2" * 32, b"3" * 32


def test_single_move_pairs() -> None:
    pairs, gone, new = pair_moves({"a/x.md": H1}, {"b/x.md": H1})
    assert (pairs, gone, new) == ([("a/x.md", "b/x.md")], [], [])


def test_unpaired_both_ways() -> None:
    pairs, gone, new = pair_moves({"a.md": H1}, {"b.md": H2})
    assert (pairs, gone, new) == ([], ["a.md"], ["b.md"])


def test_most_shared_prefix_wins_then_lexical() -> None:
    deleted = {"Projects/NAS/x.md": H1, "Archive/x.md": H1, "Projects/Other/x.md": H1}
    pairs, gone, _ = pair_moves(deleted, {"Projects/NAS/y.md": H1})
    assert pairs == [("Projects/NAS/x.md", "Projects/NAS/y.md")]
    assert gone == ["Archive/x.md", "Projects/Other/x.md"]
    pairs, _, _ = pair_moves({"b/x.md": H3, "a/x.md": H3}, {"c/x.md": H3})
    assert pairs == [("a/x.md", "c/x.md")]


def test_case_only_rename_pairs() -> None:
    assert pair_moves({"Note.md": H1}, {"note.md": H1})[0] == [("Note.md", "note.md")]


def test_guard() -> None:
    assert guard_trips(10, 40) is False
    assert guard_trips(11, 40) is True
    assert guard_trips(11, 100) is False
    assert guard_trips(0, 0) is False


def test_embed_input() -> None:
    assert embed_input("NAS", ["Disks", "RAID"], "text") == "NAS › Disks › RAID\n\ntext"
    assert embed_input("NAS", [], "text") == "NAS\n\ntext"
```

`backend/tests/unit/test_embedder.py`:

```python
from collections.abc import Callable

import pytest

from ai_second_brain.chat.providers.base import ChatTimeouts
from ai_second_brain.chat.providers.ollama import create_http_client
from ai_second_brain.knowledge.embedder import Embedder, EmbedError

from ..conftest import run_async
from ..fakes.ollama import FakeOllama, fake_vector
from ..fakes.server import closed_port_url

FAST = ChatTimeouts(connect=1.0, read=0.5, probe=0.5)
MakeFake = Callable[[], FakeOllama]


def embed(url: str, texts: list[str]) -> list[list[float]]:
    async def scenario() -> list[list[float]]:
        async with create_http_client() as client:
            return await Embedder(url, "bge-m3", 1024, client, FAST).embed(texts)

    return run_async(scenario())


def test_embeds_batch_in_order(make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    vectors = embed(fake.url, ["a", "b"])
    assert vectors == [fake_vector("a"), fake_vector("b")]
    [request] = fake.embed_requests()
    assert request.body == {"model": "bge-m3", "input": ["a", "b"]}


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"embed_status": 404, "embed_error_text": 'model "bge-m3" not found, try pulling it first'}, "embed_model_missing"),
        ({"embed_status": 500}, "embed_unreachable"),
        ({"embed_dims": 512}, "embed_bad_response"),
        ({"embed_count_delta": -1}, "embed_bad_response"),
        ({"embed_nonfinite": True}, "embed_bad_response"),
        ({"embed_status": 400, "embed_error_text": "bad"}, "embed_bad_response"),
        ({"embed_delay": 2.0}, "embed_unreachable"),
    ],
)
def test_error_codes(make_fake_ollama: MakeFake, change: dict[str, object], code: str) -> None:
    fake = make_fake_ollama()
    for name, value in change.items():
        setattr(fake.behaviour, name, value)
    with pytest.raises(EmbedError) as error:
        embed(fake.url, ["a"])
    assert error.value.code == code


def test_unreachable_host() -> None:
    with pytest.raises(EmbedError) as error:
        embed(closed_port_url(), ["a"])
    assert error.value.code == "embed_unreachable"


def test_reachable(make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()

    async def scenario(url: str) -> bool:
        async with create_http_client() as client:
            return await Embedder(url, "bge-m3", 1024, client, FAST).reachable()

    assert run_async(scenario(fake.url)) is True
    assert run_async(scenario(closed_port_url())) is False
```

Run: `uv run pytest tests/unit/test_vault_moves.py tests/unit/test_embedder.py -v`. Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement**

`backend/src/ai_second_brain/vault/moves.py`:

```python
"""Pair deleted and added paths with the same content hash (a move), and the deletion guard."""

from collections.abc import Mapping

GUARD_MIN = 10
GUARD_RATIO = 0.2


def _shared_prefix(a: str, b: str) -> int:
    count = 0
    for x, y in zip(a.split("/")[:-1], b.split("/")[:-1], strict=False):
        if x != y:
            break
        count += 1
    return count


def pair_moves(
    deleted: Mapping[str, bytes], added: Mapping[str, bytes]
) -> tuple[list[tuple[str, str]], list[str], list[str]]:
    remaining = dict(deleted)
    pairs: list[tuple[str, str]] = []
    unpaired_added: list[str] = []
    for new in sorted(added):
        candidates = [old for old, digest in remaining.items() if digest == added[new]]
        if not candidates:
            unpaired_added.append(new)
            continue
        best = min(candidates, key=lambda old: (-_shared_prefix(old, new), old))
        pairs.append((best, new))
        del remaining[best]
    return pairs, sorted(remaining), unpaired_added


def guard_trips(to_tombstone: int, live: int) -> bool:
    return to_tombstone > GUARD_MIN and to_tombstone > GUARD_RATIO * live
```

`backend/src/ai_second_brain/knowledge/embed_text.py`:

```python
from collections.abc import Sequence


def embed_input(title: str, heading_path: Sequence[str], content: str) -> str:
    head = " › ".join([title, *heading_path])
    return f"{head}\n\n{content}"
```

`backend/src/ai_second_brain/knowledge/embedder.py`:

```python
"""Ollama /api/embed client. Content-free errors; no redirects, proxies or cloud fallback."""

import math
from collections.abc import Sequence
from typing import Literal

import httpx2

from ai_second_brain.chat.providers.base import ChatTimeouts

EmbedCode = Literal["embed_unreachable", "embed_model_missing", "embed_bad_response"]


class EmbedError(Exception):
    def __init__(self, code: EmbedCode) -> None:
        super().__init__(code)
        self.code: EmbedCode = code


class EmbedRetryable(Exception):
    """embed_unreachable inside the embedding job: procrastinate retries it (Task 7)."""


class Embedder:
    def __init__(
        self, url: str, model: str, dims: int, client: httpx2.AsyncClient, timeouts: ChatTimeouts
    ) -> None:
        self.url, self.model, self.dims = url, model, dims
        self._client, self._timeouts = client, timeouts

    async def reachable(self) -> bool:
        try:
            response = await self._client.get(f"{self.url}/api/version", timeout=self._timeouts.probe)
        except (httpx2.HTTPError, httpx2.InvalidURL):
            return False
        return 200 <= response.status_code < 300

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        try:
            response = await self._client.post(
                f"{self.url}/api/embed",
                json={"model": self.model, "input": list(texts)},
                timeout=self._timeouts.http(),
            )
        except (httpx2.TimeoutException, httpx2.TransportError):
            raise EmbedError("embed_unreachable") from None
        if response.status_code >= 500:
            raise EmbedError("embed_unreachable")
        if response.status_code == 404 and "model" in response.text.lower():
            raise EmbedError("embed_model_missing")
        if response.status_code != 200:
            raise EmbedError("embed_bad_response")
        try:
            vectors = response.json()["embeddings"]
        except (ValueError, KeyError, TypeError):
            raise EmbedError("embed_bad_response") from None
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise EmbedError("embed_bad_response")
        for vector in vectors:
            if (
                not isinstance(vector, list)
                or len(vector) != self.dims
                or not all(isinstance(v, int | float) and math.isfinite(v) for v in vector)
            ):
                raise EmbedError("embed_bad_response")
        return [[float(v) for v in vector] for vector in vectors]
```

- [ ] **Step 4: Verify and commit (no push)**

Run: `uv run pytest tests/unit/test_vault_moves.py tests/unit/test_embedder.py tests/unit/test_ollama_provider.py -v` and `just backend::check`. Expected: pass (the existing Ollama provider tests still pass with the extended fake), clean.

```bash
git add backend/src/ai_second_brain/vault/moves.py backend/src/ai_second_brain/knowledge/embed_text.py backend/src/ai_second_brain/knowledge/embedder.py backend/tests/fakes/ollama.py backend/tests/unit/test_vault_moves.py backend/tests/unit/test_embedder.py
git commit -m "feat(ingest): pair moves and add the embedding client"
```

---

### Task 6: Store, queue, observe and index

**Files:**
- Create:
  - `backend/src/ai_second_brain/knowledge/context.py`, `knowledge/store.py`, `knowledge/queue.py`, `knowledge/index.py`
  - `backend/src/ai_second_brain/vault/observe.py`
  - `backend/tests/fakes/queue.py`, `backend/tests/ingest_harness.py`, `backend/tests/integration/test_ingest_index.py`
- Modify: `backend/src/ai_second_brain/knowledge/jobs.py` (the `index_source_task` body and its retry strategy)

**Interfaces:**
- Consumes: Tasks 2–5.
- Produces:
  - **`IngestContext`**: `pool`, `settings`, `vault: Vault | None`, `embedder: Embedder | None`, `queue: JobQueue`, `space_id: int`, `space_model: str`, `space_dims: int`.
  - **`JobQueue` protocol:** `index_source(source_id: UUID)`, `embed_revision(revision_id: UUID, space_id: int)`, `reconcile(run_id: int)`, `reset_stalled(seconds_since_heartbeat: int) -> int`. Implemented by `ProcrastinateQueue(app)`.
  - **`store` functions** (connection-level, async): `record_observation`, `claim_pending`, `supersede_revision`, `insert_chunks`, `delete_revision_chunks`, `finish_index`, `mark_index_failed`, `default_space`.
  - **`observe(ctx, rel) -> ObserveOutcome | None`** (None means `io_error`).
  - **`index_source(ctx, source_id)`**.
  - **Test helpers:** `RecordingQueue` and `ingest_harness(db_url, vault_root, embed_url, **settings)`.

- [ ] **Step 1: Write the context, queue and test helpers**

`backend/src/ai_second_brain/knowledge/context.py`:

```python
from dataclasses import dataclass

from psycopg_pool import AsyncConnectionPool

from ai_second_brain.config import Settings
from ai_second_brain.knowledge.embedder import Embedder
from ai_second_brain.knowledge.queue import JobQueue
from ai_second_brain.vault.paths import Vault


@dataclass(frozen=True)
class IngestContext:
    pool: AsyncConnectionPool
    settings: Settings
    vault: Vault | None
    embedder: Embedder | None
    queue: JobQueue
    space_id: int
    space_model: str
    space_dims: int
```

`backend/src/ai_second_brain/knowledge/queue.py`:

```python
"""Deferring ingest jobs. procrastinate uses its own connection, so jobs are deferred right after
the data commits; reconcile re-queues anything lost in between (plan ruling 1)."""

from typing import Protocol
from uuid import UUID

from procrastinate import App
from procrastinate.exceptions import AlreadyEnqueued


class JobQueue(Protocol):
    async def index_source(self, source_id: UUID) -> None: ...
    async def embed_revision(self, revision_id: UUID, space_id: int) -> None: ...
    async def reconcile(self, run_id: int) -> None: ...
    async def reset_stalled(self, seconds_since_heartbeat: int) -> int: ...


class ProcrastinateQueue:
    def __init__(self, app: App) -> None:
        self._app = app

    async def _defer(self, task: str, lock: str | None, **kwargs: object) -> None:
        try:
            await self._app.configure_task(task, queueing_lock=lock).defer_async(**kwargs)
        except AlreadyEnqueued:
            pass

    async def index_source(self, source_id: UUID) -> None:
        await self._defer("ingest:index_source", f"index:{source_id}", source_id=str(source_id))

    async def embed_revision(self, revision_id: UUID, space_id: int) -> None:
        await self._defer(
            "ingest:embed_revision", f"embed:{revision_id}",
            revision_id=str(revision_id), space_id=space_id,
        )

    async def reconcile(self, run_id: int) -> None:
        await self._defer("ingest:reconcile_vault", "reconcile", run_id=run_id)

    async def reset_stalled(self, seconds_since_heartbeat: int) -> int:
        stalled = await self._app.job_manager.get_stalled_jobs(
            seconds_since_heartbeat=seconds_since_heartbeat
        )
        count = 0
        for job in stalled:
            await self._app.job_manager.retry_job(job)
            count += 1
        return count
```

`backend/tests/fakes/queue.py`:

```python
from uuid import UUID


class RecordingQueue:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def index_source(self, source_id: UUID) -> None:
        self.calls.append(("index", source_id))

    async def embed_revision(self, revision_id: UUID, space_id: int) -> None:
        self.calls.append(("embed", (revision_id, space_id)))

    async def reconcile(self, run_id: int) -> None:
        self.calls.append(("reconcile", run_id))

    async def reset_stalled(self, seconds_since_heartbeat: int) -> int:
        self.calls.append(("reset_stalled", seconds_since_heartbeat))
        return 0
```

`backend/tests/ingest_harness.py`:

```python
"""Integration harness: everything lives on the loop of one run_async() call."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from procrastinate import App
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from ai_second_brain.chat.providers.base import ChatTimeouts
from ai_second_brain.chat.providers.ollama import create_http_client
from ai_second_brain.config import Settings
from ai_second_brain.knowledge.context import IngestContext
from ai_second_brain.knowledge.embedder import Embedder
from ai_second_brain.knowledge.jobs import EMBED_QUEUE, INGEST_QUEUE, create_job_app
from ai_second_brain.knowledge.queue import ProcrastinateQueue
from ai_second_brain.vault.paths import Vault

from .conftest import TEST_HASH

FAST = ChatTimeouts(connect=1.0, read=1.0, probe=0.5)
TABLES = "sources, ingest_runs, procrastinate_jobs, procrastinate_events, procrastinate_periodic_defers, procrastinate_workers"


@dataclass
class Harness:
    ctx: IngestContext
    app: App
    pool: AsyncConnectionPool

    async def drain(self) -> None:
        await self.app.run_worker_async(
            queues=[INGEST_QUEUE, EMBED_QUEUE],
            wait=False,
            concurrency=1,
            install_signal_handlers=False,
            listen_notify=False,
            additional_context={"ingest": self.ctx},
        )

    async def rows(self, sql: str, *params: Any) -> list[dict[str, Any]]:
        async with self.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return await cur.fetchall()


@asynccontextmanager
async def ingest_harness(
    db_url: str, vault_root: Path | None, embed_url: str | None, **overrides: Any
) -> AsyncIterator[Harness]:
    values: dict[str, Any] = {
        "DATABASE_URL": db_url,
        "owner_password_hash": TEST_HASH,
        "vault_path": str(vault_root) if vault_root else None,
        "embed_url_override": embed_url or "",
    }
    values.update(overrides)
    settings = Settings(_env_file=None, **values)  # pyright: ignore[reportCallIssue]
    async with AsyncConnectionPool(db_url, min_size=1, max_size=4, open=False) as pool:
        async with pool.connection() as conn:
            await conn.execute(f"TRUNCATE {TABLES} CASCADE")
        app = create_job_app(db_url)
        async with app.open_async(), create_http_client() as client:
            embedder = Embedder(embed_url, "bge-m3", 1024, client, FAST) if embed_url else None
            vault = Vault(vault_root, settings.vault_excludes) if vault_root else None
            ctx = IngestContext(
                pool, settings, vault, embedder, ProcrastinateQueue(app), 1, "bge-m3", 1024
            )
            yield Harness(ctx, app, pool)
```

- [ ] **Step 2: Write the failing integration tests**

`backend/tests/integration/test_ingest_index.py`:

```python
from collections.abc import Callable
from pathlib import Path

import pytest

from ai_second_brain.knowledge.index import index_source
from ai_second_brain.knowledge import store
from ai_second_brain.vault.observe import observe

from ..conftest import run_async
from ..fakes.ollama import FakeOllama
from ..ingest_harness import Harness, ingest_harness
from ..vaults import VaultBuilder

pytestmark = pytest.mark.integration


def run(db_url: str, root: Path, body: Callable[[Harness], object], embed_url: str | None = None) -> None:
    async def scenario() -> None:
        async with ingest_harness(db_url, root, embed_url) as h:
            await body(h)  # type: ignore[misc]

    run_async(scenario())


async def fts(h: Harness, word: str) -> list[str]:
    rows = await h.rows(
        "SELECT s.external_ref FROM chunks c JOIN sources s ON s.current_revision_id = c.revision_id"
        " WHERE s.deleted_at IS NULL AND c.tsv @@ plainto_tsquery('simple', %s) ORDER BY 1",
        word,
    )
    return [r["external_ref"] for r in rows]


def test_observe_is_idempotent_and_indexes(db_url: str, tmp_path: Path) -> None:
    vault = VaultBuilder(tmp_path)
    vault.write("NAS.md", "# NAS\nDyski w macierzy RAID\n")

    async def body(h: Harness) -> None:
        first = await observe(h.ctx, "NAS.md")
        second = await observe(h.ctx, "NAS.md")
        assert first is not None and first.action == "new"
        assert second is not None and second.action == "new"  # still pending, not yet indexed
        revisions = await h.rows("SELECT state FROM source_revisions")
        assert [r["state"] for r in revisions] == ["pending"]
        jobs = await h.rows("SELECT task_name FROM procrastinate_jobs")
        assert [j["task_name"] for j in jobs] == ["ingest:index_source"]
        await h.drain()
        assert await fts(h, "macierzy") == ["NAS.md"]
        third = await observe(h.ctx, "NAS.md")
        assert third is not None and third.action == "unchanged"

    run(db_url, tmp_path, body)


def test_edit_swaps_and_old_text_disappears(db_url: str, tmp_path: Path) -> None:
    vault = VaultBuilder(tmp_path)
    vault.write("a.md", "stary tekst")

    async def body(h: Harness) -> None:
        await observe(h.ctx, "a.md")
        await h.drain()
        vault.write("a.md", "nowy tekst")
        await observe(h.ctx, "a.md")
        await h.drain()
        assert await fts(h, "nowy") == ["a.md"]
        assert await fts(h, "stary") == []
        states = await h.rows("SELECT state, (SELECT count(*) FROM chunks c WHERE c.revision_id = r.id) AS n FROM source_revisions r ORDER BY observed_at")
        assert [(s["state"], s["n"]) for s in states] == [("superseded", 0), ("indexed", 1)]

    run(db_url, tmp_path, body)


def test_rapid_saves_index_once(db_url: str, tmp_path: Path) -> None:
    vault = VaultBuilder(tmp_path)

    async def body(h: Harness) -> None:
        for i in range(10):
            vault.write("a.md", f"wersja {i}")
            await observe(h.ctx, "a.md")
        await h.drain()
        states = await h.rows("SELECT state FROM source_revisions ORDER BY observed_at")
        assert [s["state"] for s in states] == ["superseded"] * 9 + ["indexed"]
        assert await fts(h, "9") == ["a.md"]

    run(db_url, tmp_path, body)


def test_revert_reuses_old_revision(db_url: str, tmp_path: Path) -> None:
    vault = VaultBuilder(tmp_path)

    async def body(h: Harness) -> None:
        vault.write("a.md", "A")
        await observe(h.ctx, "a.md")
        await h.drain()
        vault.write("a.md", "B")
        await observe(h.ctx, "a.md")
        await h.drain()
        vault.write("a.md", "A")
        outcome = await observe(h.ctx, "a.md")
        assert outcome is not None and outcome.action == "requeued"
        await h.drain()
        assert len(await h.rows("SELECT 1 FROM source_revisions")) == 2
        assert await fts(h, "A") == ["a.md"]

    run(db_url, tmp_path, body)


def test_crash_mid_index_rolls_back(db_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = VaultBuilder(tmp_path)
    vault.write("a.md", "pierwsza")

    async def body(h: Harness) -> None:
        await observe(h.ctx, "a.md")
        await h.drain()
        vault.write("a.md", "druga")
        outcome = await observe(h.ctx, "a.md")
        assert outcome is not None

        async def boom(*args: object, **kwargs: object) -> None:
            raise RuntimeError("injected crash after chunk insert")

        monkeypatch.setattr(store, "supersede_revision", boom)
        with pytest.raises(RuntimeError):
            await index_source(h.ctx, outcome.source_id)
        monkeypatch.undo()
        assert await fts(h, "pierwsza") == ["a.md"]
        pending = await h.rows("SELECT 1 FROM source_revisions WHERE state = 'pending'")
        assert len(pending) == 1
        await index_source(h.ctx, outcome.source_id)
        assert await fts(h, "druga") == ["a.md"]

    run(db_url, tmp_path, body)


def test_oversized_and_bad_encoding_fail_without_indexing(db_url: str, tmp_path: Path) -> None:
    vault = VaultBuilder(tmp_path)
    vault.write("big.md", "x" * 5000)
    vault.write("bad.md", b"\xff\xfe\x00bad")

    async def body(h: Harness) -> None:
        assert (await observe(h.ctx, "big.md")).action == "failed"  # type: ignore[union-attr]
        assert (await observe(h.ctx, "bad.md")).action == "failed"  # type: ignore[union-attr]
        rows = await h.rows("SELECT error FROM source_revisions ORDER BY error")
        assert [r["error"] for r in rows] == ["encoding", "too_large"]
        assert await h.rows("SELECT 1 FROM procrastinate_jobs") == []

    async def scenario() -> None:
        async with ingest_harness(db_url, tmp_path, None, max_note_bytes=1000) as h:
            await body(h)

    run_async(scenario())


def test_missing_file_is_io_error(db_url: str, tmp_path: Path) -> None:
    async def body(h: Harness) -> None:
        assert await observe(h.ctx, "ghost.md") is None
        assert await h.rows("SELECT 1 FROM sources") == []

    run(db_url, tmp_path, body)
```

Run: `just backend::test tests/integration/test_ingest_index.py -v`. Expected: FAIL (`ModuleNotFoundError: ai_second_brain.knowledge.store`).

- [ ] **Step 3: Implement the store (the index-side functions)**

`backend/src/ai_second_brain/knowledge/store.py`:

```python
"""All SQL for sources, revisions, chunks, embeddings and ingest runs. Never logs content."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ai_second_brain.vault.chunk import Chunk
from ai_second_brain.vault.read import ReadNote

ObserveAction = Literal["new", "unchanged", "requeued", "restored", "failed"]


@dataclass(frozen=True)
class ObserveOutcome:
    source_id: UUID
    action: ObserveAction
    queue_index: bool


@dataclass(frozen=True)
class Claimed:
    source_id: UUID
    revision_id: UUID
    raw_text: str
    external_ref: str
    previous_revision_id: UUID | None


async def record_observation(conn: AsyncConnection, rel: str, note: ReadNote) -> ObserveOutcome:
    meta = {"size": note.size, "mtime_ns": note.mtime_ns}
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT id, current_revision_id, deleted_at FROM sources"
            " WHERE kind = 'obsidian' AND external_ref = %s FOR UPDATE",
            (rel,),
        )
        source = await cur.fetchone()
        if source is None:
            await cur.execute(
                "INSERT INTO sources (kind, external_ref) VALUES ('obsidian', %s) RETURNING id, current_revision_id, deleted_at",
                (rel,),
            )
            source = await cur.fetchone()
        assert source is not None
        was_deleted = source["deleted_at"] is not None
        if was_deleted:
            await cur.execute("UPDATE sources SET deleted_at = NULL WHERE id = %s", (source["id"],))
        state = "failed" if note.error else "pending"
        await cur.execute(
            "INSERT INTO source_revisions (source_id, content_hash, raw_text, metadata, state, error)"
            " VALUES (%s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (source_id, content_hash) DO NOTHING RETURNING id",
            (source["id"], note.content_hash, note.text, Jsonb(meta), state, note.error),
        )
        inserted = await cur.fetchone()
        if inserted is not None:
            if note.error:
                return ObserveOutcome(source["id"], "failed", False)
            return ObserveOutcome(source["id"], "new", True)
        await cur.execute(
            "SELECT id, state FROM source_revisions WHERE source_id = %s AND content_hash = %s",
            (source["id"], note.content_hash),
        )
        existing = await cur.fetchone()
        assert existing is not None
        is_current = existing["id"] == source["current_revision_id"]
        if existing["state"] == "failed" and note.error:
            return ObserveOutcome(source["id"], "unchanged", False)
        if is_current and existing["state"] == "indexed" and not was_deleted:
            await cur.execute(
                "UPDATE source_revisions SET metadata = metadata || %s WHERE id = %s",
                (Jsonb(meta), existing["id"]),
            )
            return ObserveOutcome(source["id"], "unchanged", False)
        if existing["state"] == "pending" and not was_deleted:
            return ObserveOutcome(source["id"], "new", True)
        await cur.execute(
            "UPDATE source_revisions SET state = 'pending', error = NULL, observed_at = now(),"
            " metadata = metadata || %s WHERE id = %s",
            (Jsonb(meta), existing["id"]),
        )
        action: ObserveAction = "restored" if was_deleted and is_current else "requeued"
        return ObserveOutcome(source["id"], action, True)


async def claim_pending(conn: AsyncConnection, source_id: UUID) -> Claimed | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT external_ref, current_revision_id FROM sources WHERE id = %s FOR UPDATE",
            (source_id,),
        )
        source = await cur.fetchone()
        if source is None:
            return None
        await cur.execute(
            "SELECT id, raw_text FROM source_revisions WHERE source_id = %s AND state = 'pending'"
            " ORDER BY observed_at DESC, id DESC",
            (source_id,),
        )
        pending = await cur.fetchall()
        if not pending:
            return None
        newest, older = pending[0], pending[1:]
        if older:
            await cur.execute(
                "UPDATE source_revisions SET state = 'superseded' WHERE id = ANY(%s)",
                ([r["id"] for r in older],),
            )
        previous = source["current_revision_id"]
        return Claimed(source_id, newest["id"], newest["raw_text"], source["external_ref"],
                       previous if previous != newest["id"] else None)


async def insert_chunks(conn: AsyncConnection, revision_id: UUID, chunks: Sequence[Chunk]) -> None:
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM chunks WHERE revision_id = %s", (revision_id,))
        if chunks:
            await cur.executemany(
                "INSERT INTO chunks (revision_id, ordinal, heading_path, content) VALUES (%s, %s, %s, %s)",
                [(revision_id, c.ordinal, list(c.heading_path), c.content) for c in chunks],
            )


async def delete_revision_chunks(conn: AsyncConnection, revision_id: UUID) -> None:
    await conn.execute("DELETE FROM chunks WHERE revision_id = %s", (revision_id,))


async def supersede_revision(conn: AsyncConnection, revision_id: UUID) -> None:
    await delete_revision_chunks(conn, revision_id)
    await conn.execute("UPDATE source_revisions SET state = 'superseded' WHERE id = %s", (revision_id,))


async def finish_index(
    conn: AsyncConnection, source_id: UUID, revision_id: UUID, title: str, metadata: dict[str, Any]
) -> None:
    await conn.execute(
        "UPDATE source_revisions SET state = 'indexed', indexed_at = now(), error = NULL,"
        " metadata = (metadata - 'embed_error') || %s WHERE id = %s",
        (Jsonb(metadata), revision_id),
    )
    await conn.execute(
        "UPDATE sources SET current_revision_id = %s, title = %s WHERE id = %s",
        (revision_id, title, source_id),
    )


async def mark_index_failed(conn: AsyncConnection, source_id: UUID) -> None:
    await conn.execute(
        "UPDATE source_revisions SET state = 'failed', error = 'index_error'"
        " WHERE source_id = %s AND state = 'pending'",
        (source_id,),
    )


async def default_space(conn: AsyncConnection) -> tuple[int, str, int]:
    cur = await conn.execute("SELECT id, model, dims FROM embedding_spaces WHERE is_default")
    row = await cur.fetchone()
    if row is None:
        raise RuntimeError("no default embedding space")
    return row[0], row[1], row[2]
```

- [ ] **Step 4: Implement observe and index**

`backend/src/ai_second_brain/vault/observe.py`:

```python
"""Observe one vault file: record a revision, then queue indexing after commit."""

import asyncio
import logging

from ai_second_brain.knowledge import store
from ai_second_brain.knowledge.context import IngestContext
from ai_second_brain.knowledge.store import ObserveOutcome
from ai_second_brain.vault.read import read_note

logger = logging.getLogger("ai_second_brain.ingest")


async def observe(ctx: IngestContext, rel: str) -> ObserveOutcome | None:
    """Returns None when the file couldn't be read (io_error)."""
    assert ctx.vault is not None
    try:
        note = await asyncio.to_thread(read_note, ctx.vault.abs(rel), ctx.settings.max_note_bytes)
    except OSError:
        logger.info("observe outcome=io_error")
        return None
    async with ctx.pool.connection() as conn, conn.transaction():
        outcome = await store.record_observation(conn, rel, note)
    if outcome.queue_index:
        await ctx.queue.index_source(outcome.source_id)
    logger.info("observe source=%s action=%s", outcome.source_id, outcome.action)
    return outcome
```

`backend/src/ai_second_brain/knowledge/index.py`:

```python
"""index_source: newest pending revision → chunks → swap, in one transaction."""

import logging
from pathlib import PurePosixPath
from uuid import UUID

from ai_second_brain.knowledge import store
from ai_second_brain.knowledge.context import IngestContext
from ai_second_brain.vault.chunk import chunk_note
from ai_second_brain.vault.parse import parse_note

logger = logging.getLogger("ai_second_brain.ingest")


async def index_source(ctx: IngestContext, source_id: UUID) -> None:
    async with ctx.pool.connection() as conn, conn.transaction():
        claimed = await store.claim_pending(conn, source_id)
        if claimed is None:
            return
        parsed = parse_note(claimed.raw_text, PurePosixPath(claimed.external_ref).stem)
        chunks = chunk_note(parsed.body)
        await store.insert_chunks(conn, claimed.revision_id, chunks)
        if claimed.previous_revision_id is not None:
            await store.supersede_revision(conn, claimed.previous_revision_id)
        metadata = {
            "frontmatter": parsed.frontmatter,
            "frontmatter_error": parsed.frontmatter_error,
            "links": parsed.links,
        }
        await store.finish_index(conn, source_id, claimed.revision_id, parsed.title, metadata)
    await ctx.queue.embed_revision(claimed.revision_id, ctx.space_id)
    logger.info("index source=%s revision=%s chunks=%d", source_id, claimed.revision_id, len(chunks))
```

In `knowledge/jobs.py`, replace the `index_source_task` body and add the retry strategy (keep the other two placeholder bodies):

```python
from uuid import UUID

from procrastinate import BaseRetryStrategy, RetryDecision
from procrastinate.jobs import Job

INDEX_RETRY_SECONDS = (10, 30, 90)


class ScheduleRetry(BaseRetryStrategy):
    """Retry on the listed delays (seconds), optionally only for some exception types."""

    def __init__(self, schedule: tuple[int, ...], only: tuple[type[BaseException], ...] = ()) -> None:
        self.schedule, self.only = schedule, only

    def get_retry_decision(self, *, exception: BaseException, job: Job) -> RetryDecision | None:
        if self.only and not isinstance(exception, self.only):
            return None
        if job.attempts >= len(self.schedule):
            return None
        return RetryDecision(retry_in={"seconds": self.schedule[job.attempts]})


def _ctx(context: JobContext) -> "IngestContext":
    return context.additional_context["ingest"]


@blueprint.task(
    name="index_source", queue=INGEST_QUEUE, pass_context=True,
    retry=ScheduleRetry(INDEX_RETRY_SECONDS),
)
async def index_source_task(context: JobContext, source_id: str) -> None:
    from ai_second_brain.knowledge import store
    from ai_second_brain.knowledge.index import index_source

    ctx = _ctx(context)
    try:
        await index_source(ctx, UUID(source_id))
    except Exception:
        if context.job.attempts >= len(INDEX_RETRY_SECONDS):
            async with ctx.pool.connection() as conn:
                await store.mark_index_failed(conn, UUID(source_id))
        raise
```

(Put `from typing import TYPE_CHECKING` with `if TYPE_CHECKING: from ai_second_brain.knowledge.context import IngestContext` at the top. The function-level imports avoid an import cycle between `jobs` and `context`/`queue`.) Check `BaseRetryStrategy.get_retry_decision`'s signature in procrastinate 3.10 and match it exactly.

- [ ] **Step 5: Verify and commit (no push)**

Run: `just backend::test tests/integration/test_ingest_index.py -v` (3 times, for stability), then `just backend::test` and `just backend::check`. Expected: all pass, clean. The drain only processes `ingest` jobs that exist. `embed_revision_task` still raises `NotImplementedError`, so embed jobs fail with no retry; Task 7 implements them. **The tests here must not assert on embed jobs.**

```bash
git add backend/src/ai_second_brain/knowledge backend/src/ai_second_brain/vault/observe.py backend/tests/fakes/queue.py backend/tests/ingest_harness.py backend/tests/integration/test_ingest_index.py
git commit -m "feat(ingest): observe notes and index them"
```

---

### Task 7: Embedding job

**Files:**
- Create: `backend/src/ai_second_brain/knowledge/embed.py`, `backend/tests/integration/test_ingest_embed.py`
- Modify: `backend/src/ai_second_brain/knowledge/store.py` (the embedding functions), `backend/src/ai_second_brain/knowledge/jobs.py` (the `embed_revision_task` body)

**Interfaces:**
- Consumes: `Embedder`, `EmbedError`, `embed_input`, `IngestContext`, `ScheduleRetry`.
- Produces:
  - `EMBED_RETRY_SECONDS = (30, 60, 120, 300, 600, 1200, 2400, 3600)`;
  - `EmbedRetryable` (defined in `knowledge/embedder.py` in Task 5, re-exported from `knowledge/embed.py`);
  - `embed_revision(ctx, revision_id, space_id) -> None` (raises `EmbedRetryable` for `embed_unreachable`);
  - store: `revision_for_embedding`, `chunks_to_embed`, `write_embeddings`, `set_embed_error`, `clear_embed_error`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/integration/test_ingest_embed.py`:

```python
from collections.abc import Callable
from pathlib import Path

import pytest

from ai_second_brain.knowledge.embed import EmbedRetryable, embed_revision
from ai_second_brain.vault.observe import observe

from ..conftest import run_async
from ..fakes.ollama import FakeOllama
from ..ingest_harness import Harness, ingest_harness
from ..vaults import VaultBuilder

pytestmark = pytest.mark.integration
MakeFake = Callable[[], FakeOllama]


def long_note(sections: int) -> str:
    return "\n".join(f"# Sekcja {i}\ntreść {i} " + "słowo " * 20 for i in range(sections))


async def revision_id(h: Harness) -> object:
    [row] = await h.rows("SELECT current_revision_id AS id FROM sources")
    return row["id"]


async def embedded(h: Harness) -> tuple[int, int]:
    [row] = await h.rows(
        "SELECT count(c.id) AS total, count(e.chunk_id) AS done FROM sources s"
        " JOIN chunks c ON c.revision_id = s.current_revision_id"
        " LEFT JOIN chunk_embeddings e ON e.chunk_id = c.id AND e.space_id = 1"
    )
    return row["done"], row["total"]


def run(db_url: str, root: Path, fake: FakeOllama, body: Callable[[Harness], object], **kw: object) -> None:
    async def scenario() -> None:
        async with ingest_harness(db_url, root, fake.url, **kw) as h:
            await body(h)  # type: ignore[misc]

    run_async(scenario())


def test_embeds_all_chunks_with_title_context(db_url: str, tmp_path: Path, make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    VaultBuilder(tmp_path).write("NAS.md", long_note(3))

    async def body(h: Harness) -> None:
        await observe(h.ctx, "NAS.md")
        await h.drain()
        assert await embedded(h) == (3, 3)
        inputs = [text for r in fake.embed_requests() for text in r.body["input"]]
        assert inputs[0].startswith("NAS › Sekcja 0\n\n")

    run(db_url, tmp_path, fake, body)


def test_crash_between_batches_resumes(db_url: str, tmp_path: Path, make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    VaultBuilder(tmp_path).write("a.md", long_note(5))

    async def body(h: Harness) -> None:
        await observe(h.ctx, "a.md")
        await h.drain()  # index ok; embed batch 1 ok, batch 2 → 500 → retry scheduled later
        assert await embedded(h) == (2, 5)
        fake.behaviour.embed_fail_on_call = None
        before = len(fake.embed_requests())
        await embed_revision(h.ctx, await revision_id(h), 1)  # type: ignore[arg-type]
        assert await embedded(h) == (5, 5)
        sent = [t for r in fake.embed_requests()[before:] for t in r.body["input"]]
        assert len(sent) == 3

    fake.behaviour.embed_fail_on_call = 2
    run(db_url, tmp_path, fake, body, embed_batch=2)


def test_unreachable_keeps_text_search_and_records_code(db_url: str, tmp_path: Path, make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    VaultBuilder(tmp_path).write("a.md", "tekst do znalezienia")
    fake.behaviour.embed_status = 500

    async def body(h: Harness) -> None:
        await observe(h.ctx, "a.md")
        await h.drain()
        [row] = await h.rows(
            "SELECT r.state, r.metadata->>'embed_error' AS code FROM sources s"
            " JOIN source_revisions r ON r.id = s.current_revision_id"
        )
        assert (row["state"], row["code"]) == ("indexed", "embed_unreachable")
        assert await embedded(h) == (0, 1)
        fake.behaviour.embed_status = 200
        await embed_revision(h.ctx, await revision_id(h), 1)  # type: ignore[arg-type]
        [row] = await h.rows("SELECT r.metadata->>'embed_error' AS code FROM sources s JOIN source_revisions r ON r.id = s.current_revision_id")
        assert row["code"] is None
        assert await embedded(h) == (1, 1)

    run(db_url, tmp_path, fake, body)


def test_unreachable_raises_retryable(db_url: str, tmp_path: Path, make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    VaultBuilder(tmp_path).write("a.md", "x")

    async def body(h: Harness) -> None:
        await observe(h.ctx, "a.md")
        await h.drain()
        fake.behaviour.embed_status = 503
        await h.rows("DELETE FROM chunk_embeddings")
        with pytest.raises(EmbedRetryable):
            await embed_revision(h.ctx, await revision_id(h), 1)  # type: ignore[arg-type]

    run(db_url, tmp_path, fake, body)


def test_model_missing_is_permanent(db_url: str, tmp_path: Path, make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    fake.behaviour.embed_status = 404
    fake.behaviour.embed_error_text = 'model "bge-m3" not found, try pulling it first'
    VaultBuilder(tmp_path).write("a.md", "x")

    async def body(h: Harness) -> None:
        await observe(h.ctx, "a.md")
        await h.drain()
        [row] = await h.rows("SELECT r.metadata->>'embed_error' AS code FROM sources s JOIN source_revisions r ON r.id = s.current_revision_id")
        assert row["code"] == "embed_model_missing"
        jobs = await h.rows("SELECT status FROM procrastinate_jobs WHERE task_name = 'ingest:embed_revision'")
        assert [j["status"] for j in jobs] == ["succeeded"]  # recorded, not retried

    run(db_url, tmp_path, fake, body)


def test_empty_note_indexes_with_zero_chunks(db_url: str, tmp_path: Path, make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    VaultBuilder(tmp_path).write("empty.md", "   \n\n")

    async def body(h: Harness) -> None:
        await observe(h.ctx, "empty.md")
        await h.drain()
        [row] = await h.rows("SELECT r.state FROM sources s JOIN source_revisions r ON r.id = s.current_revision_id")
        assert row["state"] == "indexed"
        assert await embedded(h) == (0, 0)
        assert fake.embed_requests() == []

    run(db_url, tmp_path, fake, body)


def test_embed_skips_superseded_revision(db_url: str, tmp_path: Path, make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("a.md", "pierwsza")

    async def body(h: Harness) -> None:
        await observe(h.ctx, "a.md")
        await h.drain()
        old = await revision_id(h)
        vault.write("a.md", "druga")
        await observe(h.ctx, "a.md")
        await h.drain()
        before = len(fake.embed_requests())
        await embed_revision(h.ctx, old, 1)  # type: ignore[arg-type]
        assert len(fake.embed_requests()) == before

    run(db_url, tmp_path, fake, body)
```

Run: `just backend::test tests/integration/test_ingest_embed.py -v`. Expected: FAIL (`ModuleNotFoundError: ai_second_brain.knowledge.embed`).

- [ ] **Step 2: Implement**

Append to `knowledge/store.py`:

```python
@dataclass(frozen=True)
class EmbedTarget:
    title: str
    is_current: bool


async def revision_for_embedding(conn: AsyncConnection, revision_id: UUID) -> EmbedTarget | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT s.title, (s.current_revision_id = r.id AND s.deleted_at IS NULL) AS is_current"
            " FROM source_revisions r JOIN sources s ON s.id = r.source_id WHERE r.id = %s",
            (revision_id,),
        )
        row = await cur.fetchone()
    return EmbedTarget(row["title"] or "", bool(row["is_current"])) if row else None


async def chunks_to_embed(
    conn: AsyncConnection, revision_id: UUID, space_id: int
) -> list[tuple[UUID, list[str], str]]:
    cur = await conn.execute(
        "SELECT c.id, c.heading_path, c.content FROM chunks c"
        " LEFT JOIN chunk_embeddings e ON e.chunk_id = c.id AND e.space_id = %s"
        " WHERE c.revision_id = %s AND e.chunk_id IS NULL ORDER BY c.ordinal",
        (space_id, revision_id),
    )
    return [(row[0], list(row[1]), row[2]) for row in await cur.fetchall()]


async def write_embeddings(
    conn: AsyncConnection, space_id: int, rows: Sequence[tuple[UUID, list[float]]]
) -> None:
    async with conn.cursor() as cur:
        await cur.executemany(
            "INSERT INTO chunk_embeddings (chunk_id, space_id, embedding) VALUES (%s, %s, %s::halfvec)"
            " ON CONFLICT DO NOTHING",
            [(chunk_id, space_id, "[" + ",".join(repr(v) for v in vector) + "]") for chunk_id, vector in rows],
        )


async def set_embed_error(conn: AsyncConnection, revision_id: UUID, code: str) -> None:
    await conn.execute(
        "UPDATE source_revisions SET metadata = metadata || jsonb_build_object('embed_error', %s::text) WHERE id = %s",
        (code, revision_id),
    )


async def clear_embed_error(conn: AsyncConnection, revision_id: UUID) -> None:
    await conn.execute(
        "UPDATE source_revisions SET metadata = metadata - 'embed_error' WHERE id = %s", (revision_id,)
    )
```

`backend/src/ai_second_brain/knowledge/embed.py`:

```python
"""embed_revision: batch chunks to Ollama /api/embed; each batch commits on its own."""

import logging
from uuid import UUID

from ai_second_brain.knowledge import store
from ai_second_brain.knowledge.context import IngestContext
from ai_second_brain.knowledge.embed_text import embed_input
from ai_second_brain.knowledge.embedder import EmbedError, EmbedRetryable

__all__ = ["EMBED_RETRY_SECONDS", "EmbedRetryable", "embed_revision"]

logger = logging.getLogger("ai_second_brain.ingest")

EMBED_RETRY_SECONDS = (30, 60, 120, 300, 600, 1200, 2400, 3600)


async def embed_revision(ctx: IngestContext, revision_id: UUID, space_id: int) -> None:
    async with ctx.pool.connection() as conn:
        target = await store.revision_for_embedding(conn, revision_id)
        if target is None or not target.is_current:
            return
        pending = await store.chunks_to_embed(conn, revision_id, space_id)
    if not pending:
        async with ctx.pool.connection() as conn:
            await store.clear_embed_error(conn, revision_id)
        return
    if ctx.embedder is None:
        async with ctx.pool.connection() as conn:
            await store.set_embed_error(conn, revision_id, "embed_unreachable")
        raise EmbedRetryable
    batch = ctx.settings.embed_batch
    for start in range(0, len(pending), batch):
        part = pending[start : start + batch]
        texts = [embed_input(target.title, path, content) for _, path, content in part]
        try:
            vectors = await ctx.embedder.embed(texts)
        except EmbedError as error:
            async with ctx.pool.connection() as conn:
                await store.set_embed_error(conn, revision_id, error.code)
            logger.info("embed revision=%s outcome=error:%s", revision_id, error.code)
            if error.code == "embed_unreachable":
                raise EmbedRetryable from None
            return
        async with ctx.pool.connection() as conn, conn.transaction():
            await store.write_embeddings(conn, space_id, [(cid, v) for (cid, _, _), v in zip(part, vectors, strict=True)])
    async with ctx.pool.connection() as conn:
        await store.clear_embed_error(conn, revision_id)
    logger.info("embed revision=%s chunks=%d outcome=ok", revision_id, len(pending))
```

In `knowledge/jobs.py`, add `from ai_second_brain.knowledge.embedder import EmbedRetryable` at the top (`embedder` has no import cycle with `jobs`) and replace the `embed_revision_task` definition:

```python
@blueprint.task(
    name="embed_revision", queue=EMBED_QUEUE, pass_context=True,
    retry=ScheduleRetry((30, 60, 120, 300, 600, 1200, 2400, 3600), only=(EmbedRetryable,)),
)
async def embed_revision_task(context: JobContext, revision_id: str, space_id: int) -> None:
    from ai_second_brain.knowledge.embed import embed_revision

    await embed_revision(_ctx(context), UUID(revision_id), space_id)
```

- [ ] **Step 3: Verify and commit (no push)**

Run: `just backend::test tests/integration/test_ingest_embed.py tests/integration/test_ingest_index.py -v` (3 times), then `just backend::test` and `just backend::check`. Expected: pass, clean.

```bash
git add backend/src/ai_second_brain/knowledge backend/tests/integration/test_ingest_embed.py
git commit -m "feat(ingest): embed chunks with bge-m3"
```

---

### Task 8: Tombstones, moves, reconcile, the guard and recovery

**Files:**
- Create: `backend/src/ai_second_brain/vault/reconcile.py`, `backend/tests/integration/test_ingest_reconcile.py`
- Modify: `backend/src/ai_second_brain/knowledge/store.py` (tombstone, move, snapshot, recovery and run functions), `knowledge/jobs.py` (the `reconcile_vault_task` body)

**Interfaces:**
- Produces:
  - store: `LiveSource(source_id, current_hash: bytes | None, size: int | None, mtime_ns: int | None)`, `live_sources(conn) -> dict[str, LiveSource]`, `tombstone(conn, source_id)`, `path_taken(conn, rel) -> bool`, `move_source(conn, source_id, new_rel)`, `pending_sources(conn) -> list[UUID]`, `revisions_missing_embeddings(conn, space_id) -> list[UUID]`, `start_run(conn, trigger) -> int`, `finish_run(conn, run_id, outcome, counts)`;
  - `ReconcileCounts` (dataclass with the fields `seen, new, changed, moved, missing, tombstoned, requeued_index, requeued_embed, stalled_reset, io_error` and `.as_dict()`). `missing` is the number of unpaired deleted paths, whether or not the guard trips; the Sources guard banner shows it;
  - `reconcile(ctx, *, trigger: str, run_id: int | None = None, allow_mass_delete: bool = False) -> tuple[str, ReconcileCounts]`;
  - `apply_moves_and_deletes(ctx, deleted: dict[str, bytes], added: dict[str, bytes], *, guard: bool, allow_mass_delete: bool) -> MoveResult`, a dataclass with `tripped: bool`, `moved: int`, `missing: int`, `tombstoned: int` and `to_observe: list[str]`. Shared by reconcile and the watcher batch (Task 9).

- [ ] **Step 1: Write the failing tests**

`backend/tests/integration/test_ingest_reconcile.py`:

```python
from collections.abc import Callable
from pathlib import Path

import pytest

from ai_second_brain.vault.reconcile import reconcile

from ..conftest import run_async
from ..fakes.ollama import FakeOllama
from ..ingest_harness import Harness, ingest_harness
from ..vaults import VaultBuilder

pytestmark = pytest.mark.integration
MakeFake = Callable[[], FakeOllama]


def run(db_url: str, root: Path, embed_url: str | None, body: Callable[[Harness], object]) -> None:
    async def scenario() -> None:
        async with ingest_harness(db_url, root, embed_url) as h:
            await body(h)  # type: ignore[misc]

    run_async(scenario())


async def live(h: Harness) -> list[str]:
    rows = await h.rows("SELECT external_ref FROM sources WHERE deleted_at IS NULL ORDER BY 1")
    return [r["external_ref"] for r in rows]


async def last_run(h: Harness) -> dict:
    [row] = await h.rows("SELECT outcome, counts FROM ingest_runs ORDER BY id DESC LIMIT 1")
    return row


def test_initial_scan_and_offline_changes(db_url: str, tmp_path: Path, make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("a.md", "alfa")
    vault.write("b.md", "bravo")
    vault.write(".obsidian/app.md", "ignored")

    async def body(h: Harness) -> None:
        outcome, counts = await reconcile(h.ctx, trigger="startup")
        await h.drain()
        assert (outcome, counts.new) == ("ok", 2)
        assert await live(h) == ["a.md", "b.md"]
        vault.write("a.md", "alfa zmieniona")
        vault.delete("b.md")
        vault.write("c.md", "charlie")
        outcome, counts = await reconcile(h.ctx, trigger="schedule")
        await h.drain()
        assert (counts.changed, counts.new, counts.tombstoned) == (1, 1, 1)
        assert await live(h) == ["a.md", "c.md"]
        assert (await last_run(h))["outcome"] == "ok"

    run(db_url, tmp_path, fake.url, body)


def test_tombstone_restore_and_move(db_url: str, tmp_path: Path, make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("Notes/x.md", "unikalna treść")

    async def body(h: Harness) -> None:
        await reconcile(h.ctx, trigger="startup")
        await h.drain()
        [before] = await h.rows("SELECT id FROM sources")
        vault.rename("Notes/x.md", "Archive/x.md")
        _, counts = await reconcile(h.ctx, trigger="schedule")
        assert (counts.moved, counts.tombstoned, counts.new) == (1, 0, 0)
        [after] = await h.rows("SELECT id, external_ref FROM sources")
        assert after["id"] == before["id"] and after["external_ref"] == "Archive/x.md"
        assert len(await h.rows("SELECT 1 FROM source_revisions")) == 1
        vault.delete("Archive/x.md")
        await reconcile(h.ctx, trigger="schedule")
        assert await live(h) == []
        assert await h.rows("SELECT 1 FROM chunks") == []
        vault.write("Archive/x.md", "unikalna treść")
        _, counts = await reconcile(h.ctx, trigger="schedule")
        await h.drain()
        assert await live(h) == ["Archive/x.md"]
        assert len(await h.rows("SELECT 1 FROM chunks")) == 1

    run(db_url, tmp_path, fake.url, body)


def test_copy_is_not_a_move(db_url: str, tmp_path: Path, make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("a.md", "ta sama treść")

    async def body(h: Harness) -> None:
        await reconcile(h.ctx, trigger="startup")
        vault.write("copy.md", "ta sama treść")
        _, counts = await reconcile(h.ctx, trigger="schedule")
        assert (counts.moved, counts.new) == (0, 1)
        assert await live(h) == ["a.md", "copy.md"]

    run(db_url, tmp_path, fake.url, body)


def test_guard_trips_and_cli_override(db_url: str, tmp_path: Path, make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    for i in range(40):
        vault.write(f"n{i}.md", f"note {i}")

    async def body(h: Harness) -> None:
        await reconcile(h.ctx, trigger="startup")
        for i in range(11):
            vault.delete(f"n{i}.md")
        outcome, counts = await reconcile(h.ctx, trigger="schedule")
        assert (outcome, counts.tombstoned, counts.missing) == ("guard_tripped", 0, 11)
        assert (await last_run(h))["counts"]["missing"] == 11
        assert len(await live(h)) == 40
        outcome, counts = await reconcile(h.ctx, trigger="cli", allow_mass_delete=True)
        assert (outcome, counts.tombstoned) == ("ok", 11)

    run(db_url, tmp_path, fake.url, body)


def test_missing_vault_tombstones_nothing(db_url: str, tmp_path: Path, make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    root = tmp_path / "vault"
    VaultBuilder(root).write("a.md", "alfa")

    async def body(h: Harness) -> None:
        await reconcile(h.ctx, trigger="startup")
        (root / "a.md").unlink()
        root.rmdir()
        outcome, _ = await reconcile(h.ctx, trigger="schedule")
        assert outcome == "vault_unavailable"
        assert await live(h) == ["a.md"]

    run(db_url, root, fake.url, body)


def test_recovery_requeues_index_and_embed(db_url: str, tmp_path: Path, make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    VaultBuilder(tmp_path).write("a.md", "alfa")

    async def body(h: Harness) -> None:
        await reconcile(h.ctx, trigger="startup")
        await h.rows("DELETE FROM procrastinate_jobs")  # simulate a crash after commit, before defer
        _, counts = await reconcile(h.ctx, trigger="schedule")
        assert counts.requeued_index == 1
        fake.behaviour.embed_status = 500
        await h.drain()
        await h.rows("DELETE FROM procrastinate_jobs")
        fake.behaviour.embed_status = 200
        _, counts = await reconcile(h.ctx, trigger="schedule")
        assert counts.requeued_embed == 1
        await h.drain()
        assert len(await h.rows("SELECT 1 FROM chunk_embeddings")) == 1

    run(db_url, tmp_path, fake.url, body)


def test_stalled_jobs_are_reset(db_url: str, tmp_path: Path, make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    VaultBuilder(tmp_path).write("a.md", "alfa")

    async def body(h: Harness) -> None:
        await reconcile(h.ctx, trigger="startup")
        [worker] = await h.rows(
            "INSERT INTO procrastinate_workers (last_heartbeat) VALUES (now() - interval '1 hour') RETURNING id"
        )
        await h.rows(
            "UPDATE procrastinate_jobs SET status = 'doing', worker_id = %s WHERE task_name = 'ingest:index_source' RETURNING id",
            worker["id"],
        )
        _, counts = await reconcile(h.ctx, trigger="schedule")
        assert counts.stalled_reset == 1

    run(db_url, tmp_path, fake.url, body)
```

The last test's `INSERT`/`UPDATE` use procrastinate 3's `procrastinate_workers(last_heartbeat)` and `procrastinate_jobs.worker_id` columns. Confirm the names in the vendored migration; if they differ, use the vendored names.

Run: `just backend::test tests/integration/test_ingest_reconcile.py -v`. Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 2: Implement the store additions**

Append to `knowledge/store.py`:

```python
@dataclass(frozen=True)
class LiveSource:
    source_id: UUID
    current_hash: bytes | None
    size: int | None
    mtime_ns: int | None


async def live_sources(conn: AsyncConnection) -> dict[str, LiveSource]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT s.id, s.external_ref, r.content_hash,"
            " (r.metadata->>'size')::bigint AS size, (r.metadata->>'mtime_ns')::bigint AS mtime_ns"
            " FROM sources s LEFT JOIN LATERAL ("
            "   SELECT content_hash, metadata FROM source_revisions x WHERE x.source_id = s.id"
            "   ORDER BY observed_at DESC LIMIT 1) r ON true"
            " WHERE s.kind = 'obsidian' AND s.deleted_at IS NULL"
        )
        rows = await cur.fetchall()
    return {
        r["external_ref"]: LiveSource(r["id"], bytes(r["content_hash"]) if r["content_hash"] else None, r["size"], r["mtime_ns"])
        for r in rows
    }


async def tombstone(conn: AsyncConnection, source_id: UUID) -> None:
    await conn.execute(
        "DELETE FROM chunks WHERE revision_id = (SELECT current_revision_id FROM sources WHERE id = %s)",
        (source_id,),
    )
    await conn.execute("UPDATE sources SET deleted_at = now() WHERE id = %s", (source_id,))


async def path_taken(conn: AsyncConnection, rel: str) -> bool:
    cur = await conn.execute(
        "SELECT 1 FROM sources WHERE kind = 'obsidian' AND external_ref = %s", (rel,)
    )
    return await cur.fetchone() is not None


async def move_source(conn: AsyncConnection, source_id: UUID, new_rel: str) -> None:
    await conn.execute(
        "UPDATE sources SET external_ref = %s, deleted_at = NULL WHERE id = %s", (new_rel, source_id)
    )


async def pending_sources(conn: AsyncConnection) -> list[UUID]:
    cur = await conn.execute(
        "SELECT DISTINCT r.source_id FROM source_revisions r JOIN sources s ON s.id = r.source_id"
        " WHERE r.state = 'pending' AND s.deleted_at IS NULL"
    )
    return [row[0] for row in await cur.fetchall()]


async def revisions_missing_embeddings(conn: AsyncConnection, space_id: int) -> list[UUID]:
    cur = await conn.execute(
        "SELECT r.id FROM sources s JOIN source_revisions r ON r.id = s.current_revision_id"
        " WHERE s.deleted_at IS NULL AND r.state = 'indexed'"
        " AND coalesce(r.metadata->>'embed_error', '') <> 'embed_bad_response'"
        " AND EXISTS (SELECT 1 FROM chunks c LEFT JOIN chunk_embeddings e"
        "   ON e.chunk_id = c.id AND e.space_id = %s WHERE c.revision_id = r.id AND e.chunk_id IS NULL)",
        (space_id,),
    )
    return [row[0] for row in await cur.fetchall()]


async def start_run(conn: AsyncConnection, trigger: str) -> int:
    cur = await conn.execute(
        "INSERT INTO ingest_runs (trigger, started_at) VALUES (%s, now()) RETURNING id", (trigger,)
    )
    row = await cur.fetchone()
    assert row is not None
    return row[0]


async def finish_run(conn: AsyncConnection, run_id: int, outcome: str, counts: dict[str, int]) -> None:
    await conn.execute(
        "UPDATE ingest_runs SET finished_at = now(), outcome = %s, counts = %s WHERE id = %s",
        (outcome, Jsonb(counts), run_id),
    )
```

- [ ] **Step 3: Implement reconcile**

`backend/src/ai_second_brain/vault/reconcile.py`:

```python
"""One reconcile pass: vault ↔ database, moves, tombstones (guarded), and recovery."""

import asyncio
import logging
from dataclasses import asdict, dataclass

from ai_second_brain.knowledge import store
from ai_second_brain.knowledge.context import IngestContext
from ai_second_brain.vault.moves import guard_trips, pair_moves
from ai_second_brain.vault.observe import observe
from ai_second_brain.vault.read import read_note

logger = logging.getLogger("ai_second_brain.ingest")
STALLED_SECONDS = 600


@dataclass
class ReconcileCounts:
    seen: int = 0
    new: int = 0
    changed: int = 0
    moved: int = 0
    missing: int = 0
    tombstoned: int = 0
    requeued_index: int = 0
    requeued_embed: int = 0
    stalled_reset: int = 0
    io_error: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


async def _hash(ctx: IngestContext, rel: str) -> bytes | None:
    assert ctx.vault is not None
    try:
        note = await asyncio.to_thread(read_note, ctx.vault.abs(rel), ctx.settings.max_note_bytes)
    except OSError:
        return None
    return note.content_hash


@dataclass
class MoveResult:
    tripped: bool
    moved: int
    missing: int
    tombstoned: int
    to_observe: list[str]


async def apply_moves_and_deletes(
    ctx: IngestContext,
    deleted: dict[str, bytes],
    added: dict[str, bytes],
    *,
    guard: bool,
    allow_mass_delete: bool,
) -> MoveResult:
    async with ctx.pool.connection() as conn:
        live = await store.live_sources(conn)
    pairs, gone, rest = pair_moves(deleted, added)
    moved = 0
    async with ctx.pool.connection() as conn, conn.transaction():
        for old, new in pairs:
            if await store.path_taken(conn, new):
                gone.append(old)
                rest.append(new)
                continue
            await store.move_source(conn, live[old].source_id, new)
            moved += 1
    if guard and not allow_mass_delete and guard_trips(len(gone), len(live)):
        return MoveResult(True, moved, len(gone), 0, sorted(rest))
    async with ctx.pool.connection() as conn, conn.transaction():
        for rel in gone:
            await store.tombstone(conn, live[rel].source_id)
    return MoveResult(False, moved, len(gone), len(gone), sorted(rest))


async def reconcile(
    ctx: IngestContext, *, trigger: str, run_id: int | None = None, allow_mass_delete: bool = False
) -> tuple[str, ReconcileCounts]:
    counts = ReconcileCounts()
    async with ctx.pool.connection() as conn:
        if run_id is None:
            run_id = await store.start_run(conn, trigger)
    outcome = "ok"
    try:
        if ctx.vault is None:
            outcome = "disabled"
            return outcome, counts
        if not await asyncio.to_thread(ctx.vault.readable):
            outcome = "vault_unavailable"
            return outcome, counts
        on_disk = await asyncio.to_thread(ctx.vault.walk)
        counts.seen = len(on_disk)
        async with ctx.pool.connection() as conn:
            live = await store.live_sources(conn)
        new_paths = [rel for rel in on_disk if rel not in live]
        changed = [
            rel for rel, (size, mtime) in on_disk.items()
            if rel in live and (live[rel].size, live[rel].mtime_ns) != (size, mtime)
        ]
        missing = {rel: s.current_hash for rel, s in live.items() if rel not in on_disk and s.current_hash}
        added_hashes = {rel: h for rel in new_paths if (h := await _hash(ctx, rel)) is not None}
        result = await apply_moves_and_deletes(
            ctx, missing, added_hashes, guard=True, allow_mass_delete=allow_mass_delete
        )
        counts.moved, counts.missing, counts.tombstoned = result.moved, result.missing, result.tombstoned
        if result.tripped:
            outcome = "guard_tripped"
        for rel in [*result.to_observe, *changed]:
            result = await observe(ctx, rel)
            if result is None:
                counts.io_error += 1
            elif rel in changed:
                counts.changed += 1
            else:
                counts.new += 1
        async with ctx.pool.connection() as conn:
            pending = await store.pending_sources(conn)
            missing_vectors = await store.revisions_missing_embeddings(conn, ctx.space_id)
        for source_id in pending:
            await ctx.queue.index_source(source_id)
        for revision_id in missing_vectors:
            await ctx.queue.embed_revision(revision_id, ctx.space_id)
        counts.requeued_index, counts.requeued_embed = len(pending), len(missing_vectors)
        counts.stalled_reset = await ctx.queue.reset_stalled(STALLED_SECONDS)
        return outcome, counts
    except Exception as error:
        outcome = f"error:{type(error).__name__}"
        raise
    finally:
        async with ctx.pool.connection() as conn:
            await store.finish_run(conn, run_id, outcome, counts.as_dict())
        logger.info("reconcile run=%s trigger=%s outcome=%s counts=%s", run_id, trigger, outcome, counts.as_dict())
```

In `knowledge/jobs.py`, replace the `reconcile_vault_task` body:

```python
async def reconcile_vault_task(context: JobContext, run_id: int) -> None:
    from ai_second_brain.vault.reconcile import reconcile

    await reconcile(_ctx(context), trigger="manual", run_id=run_id)
```

- [ ] **Step 4: Verify and commit (no push)**

Run: `just backend::test tests/integration/test_ingest_reconcile.py -v` (3 times), then `just backend::test` and `just backend::check`. Expected: pass, clean.

```bash
git add backend/src/ai_second_brain/knowledge backend/src/ai_second_brain/vault/reconcile.py backend/tests/integration/test_ingest_reconcile.py
git commit -m "feat(ingest): reconcile the vault with guarded deletes"
```

---

### Task 9: Watcher, watcher batches and the worker process

**Files:**
- Create:
  - `backend/src/ai_second_brain/vault/watcher.py`, `vault/batch.py`, `backend/src/ai_second_brain/ingest/__init__.py`, `ingest/worker.py`
  - `backend/tests/unit/test_watcher.py`, `backend/tests/integration/test_ingest_batch.py`
- Modify: `backend/src/ai_second_brain/interfaces/cli/main.py` (the `worker` command), `backend/justfile` (`worker`), root `justfile` (`worker`, `dev`)

**Interfaces:**
- Produces:
  - `Change = Literal["added", "modified", "deleted"]`;
  - `run_watcher(vault: Vault, handle_batch: Callable[[list[tuple[Change, str]]], Awaitable[None]], stop_event: asyncio.Event, *, debounce_ms: int = 1600) -> None`;
  - `apply_batch(ctx, changes: list[tuple[Change, str]]) -> None`;
  - `async run_worker(settings: Settings, *, stop_event: asyncio.Event | None = None) -> int`;
  - CLI `ai-second-brain worker`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/unit/test_watcher.py`:

```python
import asyncio
from pathlib import Path

from ai_second_brain.runtime import new_event_loop
from ai_second_brain.vault.paths import Vault
from ai_second_brain.vault.watcher import Change, run_watcher

EXCLUDES = (".obsidian/**",)


def watch(tmp_path: Path, actions) -> set[tuple[Change, str]]:
    seen: set[tuple[Change, str]] = set()

    async def handle(batch: list[tuple[Change, str]]) -> None:
        seen.update(batch)

    async def scenario() -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(run_watcher(Vault(tmp_path, EXCLUDES), handle, stop, debounce_ms=100))
        await asyncio.sleep(0.5)
        for action in actions:
            action()
            await asyncio.sleep(0.3)
        await asyncio.sleep(1.5)
        stop.set()
        await asyncio.wait_for(task, 5)

    loop = new_event_loop()
    try:
        loop.run_until_complete(scenario())
    finally:
        loop.close()
    return seen


def test_reports_markdown_changes_only(tmp_path: Path) -> None:
    (tmp_path / ".obsidian").mkdir()
    seen = watch(tmp_path, [
        lambda: (tmp_path / "a.md").write_text("x", encoding="utf-8"),
        lambda: (tmp_path / "a.md").write_text("y", encoding="utf-8"),
        lambda: (tmp_path / "b.txt").write_text("x", encoding="utf-8"),
        lambda: (tmp_path / ".obsidian" / "c.md").write_text("x", encoding="utf-8"),
        lambda: (tmp_path / "a.md").rename(tmp_path / "renamed.md"),
    ])
    paths = {rel for _, rel in seen}
    assert "a.md" in paths and "renamed.md" in paths
    assert "b.txt" not in paths and ".obsidian/c.md" not in paths
    assert ("deleted", "a.md") in seen
```

`backend/tests/integration/test_ingest_batch.py`:

```python
from collections.abc import Callable
from pathlib import Path

import pytest

from ai_second_brain.vault.batch import apply_batch
from ai_second_brain.vault.reconcile import reconcile

from ..conftest import run_async
from ..fakes.ollama import FakeOllama
from ..ingest_harness import Harness, ingest_harness
from ..vaults import VaultBuilder

pytestmark = pytest.mark.integration
MakeFake = Callable[[], FakeOllama]


def run(db_url: str, root: Path, fake: FakeOllama, body: Callable[[Harness], object]) -> None:
    async def scenario() -> None:
        async with ingest_harness(db_url, root, fake.url) as h:
            await body(h)  # type: ignore[misc]

    run_async(scenario())


async def live(h: Harness) -> list[str]:
    return [r["external_ref"] for r in await h.rows("SELECT external_ref FROM sources WHERE deleted_at IS NULL ORDER BY 1")]


def test_apply_batch_rename_keeps_source(db_url: str, tmp_path: Path, make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("a.md", "treść")

    async def body(h: Harness) -> None:
        await reconcile(h.ctx, trigger="startup")
        [before] = await h.rows("SELECT id FROM sources")
        vault.rename("a.md", "b.md")
        await apply_batch(h.ctx, [("deleted", "a.md"), ("added", "b.md")])
        [after] = await h.rows("SELECT id, external_ref FROM sources")
        assert (after["id"], after["external_ref"]) == (before["id"], "b.md")

    run(db_url, tmp_path, fake, body)


def test_apply_batch_deleted_but_present_is_observed(db_url: str, tmp_path: Path, make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("a.md", "stara")

    async def body(h: Harness) -> None:
        await reconcile(h.ctx, trigger="startup")
        await h.drain()
        vault.write("a.md", "nowa")  # Obsidian's temp-file + rename reports delete then add
        await apply_batch(h.ctx, [("deleted", "a.md"), ("added", "a.md")])
        await h.drain()
        assert await live(h) == ["a.md"]
        rows = await h.rows("SELECT state FROM source_revisions ORDER BY observed_at")
        assert [r["state"] for r in rows] == ["superseded", "indexed"]

    run(db_url, tmp_path, fake, body)


def test_apply_batch_delete_tombstones(db_url: str, tmp_path: Path, make_fake_ollama: MakeFake) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("a.md", "x")
    vault.write("b.md", "y")

    async def body(h: Harness) -> None:
        await reconcile(h.ctx, trigger="startup")
        vault.delete("a.md")
        await apply_batch(h.ctx, [("deleted", "a.md")])
        assert await live(h) == ["b.md"]

    run(db_url, tmp_path, fake, body)
```

Run: `uv run pytest tests/unit/test_watcher.py -v` and `just backend::test tests/integration/test_ingest_batch.py -v`. Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 2: Implement the watcher and batches**

`backend/src/ai_second_brain/vault/watcher.py`:

```python
"""Watch the vault with watchfiles; restart with backoff on errors. Logs no paths."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal

from watchfiles import Change as WfChange
from watchfiles import awatch

from ai_second_brain.vault.paths import Vault

logger = logging.getLogger("ai_second_brain.ingest")
Change = Literal["added", "modified", "deleted"]
_MAP: dict[WfChange, Change] = {WfChange.added: "added", WfChange.modified: "modified", WfChange.deleted: "deleted"}


async def run_watcher(
    vault: Vault,
    handle_batch: Callable[[list[tuple[Change, str]]], Awaitable[None]],
    stop_event: asyncio.Event,
    *,
    debounce_ms: int = 1600,
) -> None:
    delay = 1.0
    while not stop_event.is_set():
        try:
            async for changes in awatch(vault.root, stop_event=stop_event, debounce=debounce_ms, recursive=True):
                batch: list[tuple[Change, str]] = []
                for kind, raw in changes:
                    rel = vault.rel(Path(raw))
                    if rel is not None and vault.is_candidate(rel):
                        batch.append((_MAP[kind], rel))
                if batch:
                    await handle_batch(sorted(set(batch)))
                delay = 1.0
        except Exception as error:  # vault vanished, permissions, handler failure
            logger.warning("watcher_error type=%s", type(error).__name__)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=delay)
            except TimeoutError:
                pass
            delay = min(delay * 2, 60.0)
```

`backend/src/ai_second_brain/vault/batch.py`:

```python
"""Apply one watcher batch: pair moves, tombstone (guarded), observe the rest."""

import asyncio

from ai_second_brain.knowledge import store
from ai_second_brain.knowledge.context import IngestContext
from ai_second_brain.vault.observe import observe
from ai_second_brain.vault.read import read_note
from ai_second_brain.vault.reconcile import apply_moves_and_deletes
from ai_second_brain.vault.watcher import Change


async def apply_batch(ctx: IngestContext, changes: list[tuple[Change, str]]) -> None:
    assert ctx.vault is not None
    exists = {rel: ctx.vault.abs(rel).is_file() for _, rel in changes}
    deleted_rels = {rel for kind, rel in changes if kind == "deleted" and not exists[rel]}
    touched = {rel for _, rel in changes if exists[rel]}
    async with ctx.pool.connection() as conn:
        live = await store.live_sources(conn)
    deleted = {rel: live[rel].current_hash for rel in deleted_rels if rel in live and live[rel].current_hash}
    new_hashes: dict[str, bytes] = {}
    for rel in sorted(touched - set(live)):
        try:
            note = await asyncio.to_thread(read_note, ctx.vault.abs(rel), ctx.settings.max_note_bytes)
        except OSError:
            continue
        new_hashes[rel] = note.content_hash
    result = await apply_moves_and_deletes(ctx, deleted, new_hashes, guard=True, allow_mass_delete=False)
    for rel in sorted(set(result.to_observe) | (touched & set(live))):
        await observe(ctx, rel)
```

- [ ] **Step 3: Implement the worker process and CLI**

`backend/src/ai_second_brain/ingest/__init__.py`: `"""The ingestion worker process."""`

`backend/src/ai_second_brain/ingest/worker.py`:

```python
"""`ai-second-brain worker`: procrastinate worker + watcher + reconcile timer, one process."""

import asyncio
import contextlib
import logging
import signal

from ai_second_brain.chat.providers.base import ChatTimeouts
from ai_second_brain.chat.providers.ollama import create_http_client
from ai_second_brain.config import Settings, model_matches_space
from ai_second_brain.db import create_pool
from ai_second_brain.knowledge import store
from ai_second_brain.knowledge.context import IngestContext
from ai_second_brain.knowledge.embedder import Embedder
from ai_second_brain.knowledge.jobs import EMBED_QUEUE, INGEST_QUEUE, create_job_app
from ai_second_brain.knowledge.queue import ProcrastinateQueue
from ai_second_brain.vault.batch import apply_batch
from ai_second_brain.vault.paths import Vault
from ai_second_brain.vault.reconcile import reconcile
from ai_second_brain.vault.watcher import run_watcher

logger = logging.getLogger("ai_second_brain.ingest")


def _install_signals(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(ValueError, OSError):
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))


async def _reconcile_loop(ctx: IngestContext, stop: asyncio.Event) -> None:
    await reconcile(ctx, trigger="startup")
    while not stop.is_set():
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=ctx.settings.reconcile_minutes * 60)
        if not stop.is_set():
            try:
                await reconcile(ctx, trigger="schedule")
            except Exception as error:
                logger.warning("reconcile_error type=%s", type(error).__name__)


async def run_worker(settings: Settings, *, stop_event: asyncio.Event | None = None) -> int:
    stop = stop_event or asyncio.Event()
    if stop_event is None:
        _install_signals(stop)
    pool = create_pool(settings.database_url)
    await pool.open(wait=True, timeout=30)
    try:
        async with pool.connection() as conn:
            space_id, model, dims = await store.default_space(conn)
        if not model_matches_space(settings.embed_model, model):
            logger.error("embed_model_mismatch configured=%s default_space=%s", settings.embed_model, model)
            print(f"SB_EMBED_MODEL={settings.embed_model!r} is not a tag of the default embedding space {model!r}.")
            return 1
        app = create_job_app(settings.database_url)
        async with app.open_async(), create_http_client() as client:
            embedder = (
                Embedder(settings.embed_url, settings.embed_model, dims, client, ChatTimeouts())
                if settings.embed_url else None
            )
            vault = Vault(settings.vault_path, settings.vault_excludes) if settings.vault_path else None
            ctx = IngestContext(pool, settings, vault, embedder, ProcrastinateQueue(app), space_id, model, dims)
            worker = asyncio.create_task(app.run_worker_async(
                queues=[INGEST_QUEUE, EMBED_QUEUE], concurrency=2, install_signal_handlers=False,
                shutdown_graceful_timeout=30, additional_context={"ingest": ctx},
            ))
            helpers: list[asyncio.Task[None]] = []
            if vault is None:
                await reconcile(ctx, trigger="startup")  # records outcome 'disabled'
            else:
                helpers.append(asyncio.create_task(_reconcile_loop(ctx, stop)))
                helpers.append(asyncio.create_task(run_watcher(vault, lambda b: apply_batch(ctx, b), stop)))
            await stop.wait()
            for task in helpers:
                task.cancel()
            worker.cancel()
            for task in [*helpers, worker]:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        return 0
    finally:
        await pool.close()
```

In `interfaces/cli/main.py`, add:

```python
@app.command()
def worker() -> None:
    """Run the ingestion worker (jobs + vault watcher + reconcile). Ctrl+C to stop."""
    from ai_second_brain.ingest.worker import run_worker

    try:
        settings = get_settings()
    except ValidationError as error:
        typer.echo(f"Configuration error:\n{error}", err=True)
        raise typer.Exit(code=1) from error
    logging.config.dictConfig(build_log_config())
    code = asyncio.run(run_worker(settings), loop_factory=new_event_loop)
    raise typer.Exit(code=code)
```

(Add `import logging.config` at the top.)

`backend/justfile`, add:

```just
# Run the ingestion worker (jobs, vault watcher, reconcile)
worker:
    uv run ai-second-brain worker
```

Root `justfile`: add a `worker` recipe, and change `dev` so it runs three processes:

```just
# Run the ingestion worker alone
worker:
    just backend::worker

# Run API (reload), web dev server and ingestion worker together; open http://localhost:5173
dev:
    just db::up
    pnpm exec concurrently --names api,web,worker --prefix-colors blue,magenta,green --kill-others-on-fail "just backend::serve --reload" "just web::dev" "just backend::worker"
```

- [ ] **Step 4: Verify and commit (no push)**

Run: `uv run pytest tests/unit/test_watcher.py -v` (3 times; if the rename assertion flakes on one platform because of event coalescing, widen the sleeps a little but keep the assertions), `just backend::test tests/integration/test_ingest_batch.py -v`, `just backend::test` and `just backend::check`. Expected: pass, clean.

Manual smoke (not a test): set `SB_VAULT_PATH` in `.env` to a small test folder and run `just worker`. Expected: it logs a startup reconcile; editing a note logs `observe … action=new`; Ctrl+C exits within about 30 s.

```bash
git add backend/src/ai_second_brain/vault backend/src/ai_second_brain/ingest backend/src/ai_second_brain/interfaces/cli/main.py backend/justfile justfile backend/tests/unit/test_watcher.py backend/tests/integration/test_ingest_batch.py
git commit -m "feat(ingest): add the vault watcher and worker process"
```

---

### Task 10: Sources API and the vault CLI

**Files:**
- Create: `backend/src/ai_second_brain/knowledge/status.py`, `backend/src/ai_second_brain/interfaces/api/routes/sources.py`, `backend/tests/integration/test_sources_api.py`, `backend/tests/unit/test_cli_vault.py`
- Modify: `interfaces/api/schemas.py`, `interfaces/api/app.py` (a job app in the lifespan + the router), `interfaces/cli/main.py` (`vault reconcile`, `vault status`), `backend/tests/unit/test_cli.py` (operation ids), root `justfile` (`vault-scan`, `vault-status`)
- Regenerate: `web/src/api/*`

**Interfaces:**
- Produces:
  - `status.summary(conn, settings, space_id, host_reachable: bool | None) -> SourcesSummary`;
  - `status.list_sources(conn, space_id, *, state, q, cursor) -> SourceList`;
  - `status.retry_source(conn, source_id, space_id) -> tuple[RetryKind, UUID | None]` where `RetryKind = Literal["index", "embed", "none", "missing"]`;
  - operation ids `sourcesSummary`, `listSources`, `retrySource`, `reconcileVault`;
  - schemas `SourcesSummary`, `SourceRow`, `SourceList`, `ReconcileQueued`;
  - CLI `vault reconcile [--allow-mass-delete]` and `vault status`; recipes `just vault-scan` and `just vault-status`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/integration/test_sources_api.py`:

```python
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from ai_second_brain.config import Settings
from ai_second_brain.interfaces.api.app import create_app
from ai_second_brain.vault.reconcile import reconcile

from ..conftest import SAME_ORIGIN, TEST_PASSWORD, make_client, run_async
from ..fakes.ollama import FakeOllama
from ..ingest_harness import ingest_harness
from ..vaults import VaultBuilder

pytestmark = pytest.mark.integration
EVIL = {"Origin": "https://evil.example"}


@pytest.fixture
def db(db_url: str) -> Iterator[None]:
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("TRUNCATE auth_sessions, sources, ingest_runs, procrastinate_jobs CASCADE")
    yield


@pytest.fixture
def make_api(make_settings: Callable[..., Settings], db_url: str, db: None) -> Iterator[Callable[..., TestClient]]:
    with ExitStack() as stack:

        def _make(*, login: bool = True, **settings: Any) -> TestClient:
            client = stack.enter_context(make_client(create_app(make_settings(DATABASE_URL=db_url, **settings))))
            if login:
                assert client.post("/api/auth/login", json={"password": TEST_PASSWORD}, headers=SAME_ORIGIN).status_code == 204
            return client

        yield _make


def seed(db_url: str, root: Path, embed_url: str, drain: bool = True) -> None:
    async def scenario() -> None:
        async with ingest_harness(db_url, root, embed_url) as h:
            await reconcile(h.ctx, trigger="startup")
            if drain:
                await h.drain()

    run_async(scenario())


def test_summary_and_list(make_api: Callable[..., TestClient], db_url: str, tmp_path: Path, make_fake_ollama: Callable[[], FakeOllama]) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    vault.write("Projects/NAS.md", "# NAS\ndyski")
    vault.write("big.md", "x" * 3_000_000)
    seed(db_url, tmp_path, fake.url)
    client = make_api(vault_path=str(tmp_path), embed_url_override=fake.url)
    summary = client.get("/api/sources/summary").json()
    assert summary["vault"] == {"configured": True, "readable": True}
    assert summary["sources"] == {"active": 2, "deleted": 0}
    assert summary["revisions"]["indexed"] == 1 and summary["revisions"]["failed"] == 1
    assert summary["embedding"]["model"] == "bge-m3"
    assert summary["embedding"]["embedded"] == summary["embedding"]["total"] == 1
    assert summary["embedding"]["host_reachable"] is True
    assert summary["last_run"]["outcome"] == "ok"
    listing = client.get("/api/sources").json()
    assert [(r["path"], r["state"], r["chunks"], r["embedded"]) for r in listing["items"]] == [
        ("Projects/NAS.md", "indexed", 1, 1),
        ("big.md", "failed", 0, 0),
    ]
    assert listing["items"][1]["error"] == "too_large"
    assert client.get("/api/sources", params={"state": "failed"}).json()["items"][0]["path"] == "big.md"
    assert [r["path"] for r in client.get("/api/sources", params={"q": "nas"}).json()["items"]] == ["Projects/NAS.md"]


def test_cursor_pagination(make_api: Callable[..., TestClient], db_url: str, tmp_path: Path, make_fake_ollama: Callable[[], FakeOllama]) -> None:
    fake = make_fake_ollama()
    vault = VaultBuilder(tmp_path)
    for i in range(55):
        vault.write(f"n{i:02d}.md", f"note {i}")
    seed(db_url, tmp_path, fake.url, drain=False)
    client = make_api(vault_path=str(tmp_path))
    first = client.get("/api/sources").json()
    assert len(first["items"]) == 50 and first["next_cursor"]
    second = client.get("/api/sources", params={"cursor": first["next_cursor"]}).json()
    assert [r["path"] for r in second["items"]] == [f"n{i}.md" for i in range(50, 55)]
    assert second["next_cursor"] is None


def test_retry_and_reconcile(make_api: Callable[..., TestClient], db_url: str, tmp_path: Path, make_fake_ollama: Callable[[], FakeOllama]) -> None:
    fake = make_fake_ollama()
    fake.behaviour.embed_status = 404
    fake.behaviour.embed_error_text = "model not found"
    VaultBuilder(tmp_path).write("a.md", "x")
    seed(db_url, tmp_path, fake.url)
    client = make_api(vault_path=str(tmp_path), embed_url_override=fake.url)
    [row] = client.get("/api/sources").json()["items"]
    assert client.get("/api/sources/summary").json()["embedding"]["last_error"] == "embed_model_missing"
    assert client.post(f"/api/sources/{row['id']}/retry", headers=SAME_ORIGIN).status_code == 202
    assert client.post(f"/api/sources/{row['id']}/retry", headers=SAME_ORIGIN).status_code == 202  # still missing vectors
    missing = client.post("/api/sources/00000000-0000-4000-8000-000000000000/retry", headers=SAME_ORIGIN)
    assert (missing.status_code, missing.json()) == (404, {"detail": "not_found"})
    queued = client.post("/api/sources/reconcile", headers=SAME_ORIGIN)
    assert queued.status_code == 202 and isinstance(queued.json()["run_id"], int)
    disabled = make_api().post("/api/sources/reconcile", headers=SAME_ORIGIN)
    assert (disabled.status_code, disabled.json()) == (409, {"detail": "vault_disabled"})


def test_nothing_to_retry(make_api: Callable[..., TestClient], db_url: str, tmp_path: Path, make_fake_ollama: Callable[[], FakeOllama]) -> None:
    fake = make_fake_ollama()
    VaultBuilder(tmp_path).write("a.md", "x")
    seed(db_url, tmp_path, fake.url)
    client = make_api(vault_path=str(tmp_path))
    [row] = client.get("/api/sources").json()["items"]
    response = client.post(f"/api/sources/{row['id']}/retry", headers=SAME_ORIGIN)
    assert (response.status_code, response.json()) == (409, {"detail": "nothing_to_retry"})


def test_auth_and_csrf(make_api: Callable[..., TestClient]) -> None:
    client = make_api()
    assert client.post("/api/sources/reconcile", headers=EVIL).status_code == 403
    anonymous = make_api(login=False)
    for method, path in [("GET", "/api/sources/summary"), ("GET", "/api/sources"), ("POST", "/api/sources/reconcile")]:
        assert anonymous.request(method, path, headers=SAME_ORIGIN).status_code == 401
```

`backend/tests/unit/test_cli_vault.py`:

```python
from collections.abc import Callable

import pytest
from typer.testing import CliRunner

from ai_second_brain.config import Settings
from ai_second_brain.interfaces.cli import main
from ai_second_brain.interfaces.cli.main import app

runner = CliRunner()


def test_vault_commands_explain_missing_vault(monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings]) -> None:
    monkeypatch.setattr(main, "get_settings", lambda: make_settings())
    result = runner.invoke(app, ["vault", "reconcile"])
    assert result.exit_code == 1
    assert "SB_VAULT_PATH" in result.output
```

Also add `"sourcesSummary", "listSources", "retrySource", "reconcileVault"` to the expected operation ids in `backend/tests/unit/test_cli.py`.

Run the new tests. Expected: FAIL (404s / `No such command 'vault'`).

- [ ] **Step 2: Implement the status queries**

`backend/src/ai_second_brain/knowledge/status.py`:

```python
"""Read models for the Sources API and CLI."""

import base64
from collections import Counter
from typing import Any, Literal
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from ai_second_brain.config import Settings

PAGE = 50
STATE_SQL = "CASE WHEN s.deleted_at IS NOT NULL THEN 'deleted' ELSE lr.state::text END"


def encode_cursor(ref: str) -> str:
    return base64.urlsafe_b64encode(ref.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> str:
    return base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()


async def _one(conn: AsyncConnection, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, params)
        row = await cur.fetchone()
    return row or {}


async def summary(conn: AsyncConnection, settings: Settings, space_id: int, host_reachable: bool | None) -> dict[str, Any]:
    vault = settings.vault_path
    readable = bool(vault and vault.is_dir())
    sources = await _one(conn, "SELECT count(*) FILTER (WHERE deleted_at IS NULL) AS active, count(*) FILTER (WHERE deleted_at IS NOT NULL) AS deleted FROM sources")
    revisions = await _one(conn,
        "SELECT count(*) FILTER (WHERE lr.state = 'pending') AS pending,"
        " count(*) FILTER (WHERE lr.state = 'indexed') AS indexed,"
        " count(*) FILTER (WHERE lr.state = 'failed') AS failed"
        " FROM sources s JOIN LATERAL (SELECT state FROM source_revisions r WHERE r.source_id = s.id"
        " ORDER BY observed_at DESC LIMIT 1) lr ON true WHERE s.deleted_at IS NULL")
    embedding = await _one(conn,
        "SELECT count(c.id) AS total, count(e.chunk_id) AS embedded FROM sources s"
        " JOIN chunks c ON c.revision_id = s.current_revision_id"
        " LEFT JOIN chunk_embeddings e ON e.chunk_id = c.id AND e.space_id = %s WHERE s.deleted_at IS NULL",
        (space_id,))
    space = await _one(conn, "SELECT model FROM embedding_spaces WHERE id = %s", (space_id,))
    errors_cur = await conn.execute(
        "SELECT r.metadata->>'embed_error' FROM sources s JOIN source_revisions r ON r.id = s.current_revision_id"
        " WHERE s.deleted_at IS NULL AND r.metadata ? 'embed_error'")
    errors = Counter(row[0] for row in await errors_cur.fetchall())
    jobs = await _one(conn,
        "SELECT count(*) FILTER (WHERE status IN ('todo', 'doing')) AS waiting,"
        " count(*) FILTER (WHERE status = 'failed') AS failed FROM procrastinate_jobs WHERE queue_name IN ('ingest', 'embed')")
    last = await _one(conn, "SELECT trigger, started_at, finished_at, outcome, counts FROM ingest_runs ORDER BY id DESC LIMIT 1")
    return {
        "vault": {"configured": vault is not None, "readable": readable},
        "sources": {"active": sources["active"], "deleted": sources["deleted"]},
        "revisions": {k: revisions.get(k) or 0 for k in ("pending", "indexed", "failed")},
        "chunks": embedding.get("total") or 0,
        "embedding": {
            "model": space.get("model", settings.embed_model),
            "embedded": embedding.get("embedded") or 0,
            "total": embedding.get("total") or 0,
            "host_reachable": host_reachable,
            "last_error": errors.most_common(1)[0][0] if errors else None,
        },
        "jobs": {"waiting": jobs.get("waiting") or 0, "failed": jobs.get("failed") or 0},
        "last_run": last or None,
    }


async def list_sources(
    conn: AsyncConnection, space_id: int, *, state: str | None, q: str | None, cursor: str | None
) -> dict[str, Any]:
    after = decode_cursor(cursor) if cursor else None
    pattern = f"%{q}%" if q else None
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            f"SELECT * FROM (SELECT s.id, s.title, s.external_ref AS path, {STATE_SQL} AS state,"  # noqa: S608
            " coalesce(lr.error, cur.metadata->>'embed_error') AS error, cur.indexed_at,"
            " (SELECT count(*) FROM chunks c WHERE c.revision_id = s.current_revision_id AND s.deleted_at IS NULL) AS chunks,"
            " (SELECT count(*) FROM chunks c JOIN chunk_embeddings e ON e.chunk_id = c.id AND e.space_id = %(space)s"
            "   WHERE c.revision_id = s.current_revision_id AND s.deleted_at IS NULL) AS embedded"
            " FROM sources s LEFT JOIN source_revisions cur ON cur.id = s.current_revision_id"
            " LEFT JOIN LATERAL (SELECT state, error FROM source_revisions r WHERE r.source_id = s.id"
            "   ORDER BY observed_at DESC LIMIT 1) lr ON true) x"
            " WHERE (%(state)s::text IS NULL OR x.state = %(state)s)"
            " AND (%(pattern)s::text IS NULL OR x.path ILIKE %(pattern)s OR x.title ILIKE %(pattern)s)"
            " AND (%(after)s::text IS NULL OR x.path COLLATE \"C\" > %(after)s COLLATE \"C\")"
            " ORDER BY x.path COLLATE \"C\" LIMIT %(limit)s",
            {"space": space_id, "state": state, "pattern": pattern, "after": after, "limit": PAGE + 1},
        )
        rows = await cur.fetchall()
    items, more = rows[:PAGE], len(rows) > PAGE
    return {"items": items, "next_cursor": encode_cursor(items[-1]["path"]) if more else None}


RetryKind = Literal["index", "embed", "none", "missing"]


async def retry_source(conn: AsyncConnection, source_id: UUID, space_id: int) -> tuple[RetryKind, UUID | None]:
    """Returns what to queue: ('index', None), ('embed', current_revision_id), ('none'|'missing', None)."""
    row = await _one(conn,
        "SELECT s.current_revision_id, lr.id AS latest_id, lr.state FROM sources s"
        " LEFT JOIN LATERAL (SELECT id, state FROM source_revisions r WHERE r.source_id = s.id"
        " ORDER BY observed_at DESC LIMIT 1) lr ON true WHERE s.id = %s", (source_id,))
    if not row:
        return "missing", None
    if row["state"] == "failed":
        await conn.execute("UPDATE source_revisions SET state = 'pending', error = NULL WHERE id = %s", (row["latest_id"],))
        return "index", None
    current = row["current_revision_id"]
    if current is None:
        return "none", None
    missing = await _one(conn,
        "SELECT count(*) AS n FROM chunks c LEFT JOIN chunk_embeddings e ON e.chunk_id = c.id AND e.space_id = %s"
        " WHERE c.revision_id = %s AND e.chunk_id IS NULL", (space_id, current))
    if missing.get("n"):
        await conn.execute("UPDATE source_revisions SET metadata = metadata - 'embed_error' WHERE id = %s", (current,))
        return "embed", current
    return "none", None
```

- [ ] **Step 3: Implement the API and CLI**

Append to `interfaces/api/schemas.py`:

```python
class VaultState(BaseModel):
    configured: bool
    readable: bool


class SourceCounts(BaseModel):
    active: int
    deleted: int


class RevisionCounts(BaseModel):
    pending: int
    indexed: int
    failed: int


class EmbeddingState(BaseModel):
    model: str
    embedded: int
    total: int
    host_reachable: bool | None
    last_error: str | None


class JobCounts(BaseModel):
    waiting: int
    failed: int


class IngestRun(BaseModel):
    trigger: str
    started_at: datetime
    finished_at: datetime | None
    outcome: str | None
    counts: dict[str, int]


class SourcesSummary(BaseModel):
    vault: VaultState
    sources: SourceCounts
    revisions: RevisionCounts
    chunks: int
    embedding: EmbeddingState
    jobs: JobCounts
    last_run: IngestRun | None


class SourceRow(BaseModel):
    id: UUID
    title: str | None
    path: str
    state: Literal["pending", "indexed", "failed", "superseded", "deleted"]
    error: str | None
    indexed_at: datetime | None
    chunks: int
    embedded: int


class SourceList(BaseModel):
    items: list[SourceRow]
    next_cursor: str | None


class ReconcileQueued(BaseModel):
    run_id: int
```

(Add `from uuid import UUID` if it's missing.)

`backend/src/ai_second_brain/interfaces/api/routes/sources.py`:

```python
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from ai_second_brain.knowledge import status as read, store
from ai_second_brain.interfaces.api.deps import get_settings, require_same_origin, require_session
from ai_second_brain.interfaces.api.schemas import ErrorResponse, ReconcileQueued, SourceList, SourcesSummary

router = APIRouter(tags=["sources"], dependencies=[Depends(require_session)])
ERRORS: dict[int | str, dict[str, Any]] = {k: {"model": ErrorResponse} for k in (401, 403, 422, 503)}


@router.get("/sources/summary", operation_id="sourcesSummary", response_model=SourcesSummary, responses=ERRORS)
async def sources_summary(request: Request) -> Any:
    ingest = request.app.state.ingest
    reachable = await ingest.host_reachable()
    async with request.app.state.pool.connection() as conn:
        return await read.summary(conn, get_settings(request), ingest.space_id, reachable)


@router.get("/sources", operation_id="listSources", response_model=SourceList, responses=ERRORS)
async def list_sources(
    request: Request,
    state: Literal["pending", "indexed", "failed", "deleted"] | None = None,
    q: str | None = Query(default=None, max_length=200),
    cursor: str | None = Query(default=None, max_length=500),
) -> Any:
    async with request.app.state.pool.connection() as conn:
        return await read.list_sources(conn, request.app.state.ingest.space_id, state=state, q=q, cursor=cursor)


@router.post(
    "/sources/{source_id}/retry", operation_id="retrySource", status_code=status.HTTP_202_ACCEPTED,
    response_class=Response, dependencies=[Depends(require_same_origin)],
    responses={**ERRORS, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def retry_source(source_id: UUID, request: Request) -> None:
    ingest = request.app.state.ingest
    async with request.app.state.pool.connection() as conn:
        kind, revision_id = await read.retry_source(conn, source_id, ingest.space_id)
    if kind == "missing":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not_found")
    if kind == "none":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="nothing_to_retry")
    if kind == "index":
        await ingest.queue.index_source(source_id)
    elif revision_id is not None:
        await ingest.queue.embed_revision(revision_id, ingest.space_id)


@router.post(
    "/sources/reconcile", operation_id="reconcileVault", status_code=status.HTTP_202_ACCEPTED,
    response_model=ReconcileQueued, dependencies=[Depends(require_same_origin)],
    responses={**ERRORS, 409: {"model": ErrorResponse}},
)
async def reconcile_vault(request: Request) -> ReconcileQueued:
    if get_settings(request).vault_path is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="vault_disabled")
    async with request.app.state.pool.connection() as conn:
        run_id = await store.start_run(conn, "manual")
    await request.app.state.ingest.queue.reconcile(run_id)
    return ReconcileQueued(run_id=run_id)
```

In `interfaces/api/app.py`:
- Add an `IngestAccess` holder class in the same module:

```python
@dataclass
class IngestAccess:
    queue: ProcrastinateQueue
    space_id: int
    embedder: Embedder | None
    _cache: tuple[float, bool] | None = None

    async def host_reachable(self) -> bool | None:
        if self.embedder is None:
            return None
        now = time.monotonic()
        if self._cache and now - self._cache[0] < 10:
            return self._cache[1]
        result = await self.embedder.reachable()
        self._cache = (now, result)
        return result
```

- In the lifespan, after the chat wiring, build the job app, open it, and set `app.state.ingest`:

```python
        job_app = create_job_app(settings.database_url)
        await job_app.open_async()
        embedder = (
            Embedder(settings.embed_url, settings.embed_model, 1024, http_client, timeouts)
            if settings.embed_url else None
        )
        app.state.ingest = IngestAccess(ProcrastinateQueue(job_app), 1, embedder)
```

  The space id is 1, as seeded by the migration. Close the job app in the `finally` block (`await job_app.close_async()`) before the pool. `job_app.open_async()` connects lazily. If the database is down at startup the API must still start, so wrap the open in `contextlib.suppress(Exception)`, log `job_app_unavailable`, and let the routes fail with 503.
- Include the router: `app.include_router(sources.router, prefix="/api")`.

In `interfaces/cli/main.py`, add a sub-app:

```python
vault_app = typer.Typer(no_args_is_help=True, help="Vault ingestion commands.")
app.add_typer(vault_app, name="vault")


async def _cli_context(settings: Settings):  # returns (ctx, cleanup) — see below
    ...
```

Implement `vault reconcile` and `vault status` with `asyncio.run(..., loop_factory=new_event_loop)`:
- **`vault reconcile [--allow-mass-delete]`:**
  - no `SB_VAULT_PATH` → print "No vault configured. Set SB_VAULT_PATH in .env." and exit 1;
  - otherwise build the same `IngestContext` as the worker (pool, job app, `ProcrastinateQueue`, embedder, `Vault`) inside `async with`, run `reconcile(ctx, trigger="cli", allow_mass_delete=flag)`, print `outcome` and each count as `name: value`, and exit 1 unless the outcome is `ok`.
- **`vault status`:** open a pool, run `status.summary(conn, settings, 1, None)`, and print it as aligned `key: value` lines.

Root `justfile`:

```just
# One reconcile pass now (pass --allow-mass-delete via: just vault-scan --allow-mass-delete)
vault-scan *args:
    uv run --directory backend ai-second-brain vault reconcile {{ args }}

# Print ingestion status
vault-status:
    uv run --directory backend ai-second-brain vault status
```

- [ ] **Step 4: Verify and commit (no push)**

Run: `just backend::test tests/integration/test_sources_api.py tests/unit/test_cli_vault.py tests/unit/test_cli.py -v`, then `just backend::test`, `just api-client` and `just check`. Expected: pass, clean.

```bash
git add backend/src backend/tests justfile web/src/api
git commit -m "feat(api): add sources status endpoints and vault CLI"
```

---

### Task 11: Web Sources screen

**Files:**
- Create: `web/src/features/sources/{types.ts,api.ts,labels.ts,SourcesScreen.tsx,SourcesScreen.test.tsx}`
- Modify: `web/src/routes/_app/sources.tsx` (replace the placeholder), `web/src/design-system/tokens.css` (map the ingest tokens)

**Interfaces:**
- Consumes: the generated `components["schemas"]` `SourcesSummary`, `SourceList`, `SourceRow`, `ReconcileQueued`; API paths `/api/sources/summary`, `/api/sources`, `/api/sources/{source_id}/retry`, `/api/sources/reconcile`.
- Produces:
  - `SourcesScreen({ summary, list, onRetry, onScan, onFilter, onLoadMore, scanPending })`, a presentational component;
  - `badgeFor(row) -> {label, tone}`, `bannersFor(summary) -> string[]`, `relativeTime(iso, now)`;
  - the route `/sources` wiring queries and mutations.

- [ ] **Step 1: Map the tokens**

In `tokens.css` `@theme inline`, add:

```css
  --color-ingest-pending-fg: var(--sb-ingest-pending-fg);
  --color-ingest-pending-bg: var(--sb-ingest-pending-bg);
  --color-ingest-pending-border: var(--sb-ingest-pending-border);
  --color-ingest-searchable-fg: var(--sb-ingest-searchable-fg);
  --color-ingest-searchable-bg: var(--sb-ingest-searchable-bg);
  --color-ingest-searchable-border: var(--sb-ingest-searchable-border);
  --color-ingest-failed-fg: var(--sb-ingest-failed-fg);
  --color-ingest-failed-bg: var(--sb-ingest-failed-bg);
  --color-ingest-failed-border: var(--sb-ingest-failed-border);
```

- [ ] **Step 2: Write the failing tests**

`web/src/features/sources/SourcesScreen.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { badgeFor, bannersFor } from "./labels";
import { SourcesScreen } from "./SourcesScreen";
import type { SourceRow, SourcesSummary } from "./types";

const BASE: SourcesSummary = {
  vault: { configured: true, readable: true },
  sources: { active: 3, deleted: 0 },
  revisions: { pending: 1, indexed: 1, failed: 1 },
  chunks: 10,
  embedding: { model: "bge-m3", embedded: 9, total: 10, host_reachable: true, last_error: null },
  jobs: { waiting: 1, failed: 0 },
  last_run: { trigger: "schedule", started_at: "2026-09-30T10:00:00Z", finished_at: "2026-09-30T10:00:02Z", outcome: "ok", counts: { changed: 3 } },
};
const row = (over: Partial<SourceRow>): SourceRow => ({
  id: crypto.randomUUID(), title: "NAS", path: "Projects/NAS.md", state: "indexed",
  error: null, indexed_at: "2026-09-30T10:00:00Z", chunks: 2, embedded: 2, ...over,
});

describe("labels", () => {
  it("maps rows to badges", () => {
    expect(badgeFor(row({})).label).toBe("Searchable");
    expect(badgeFor(row({ embedded: 1 })).label).toBe("Text only");
    expect(badgeFor(row({ state: "pending" })).label).toBe("Waiting");
    expect(badgeFor(row({ state: "failed", error: "too_large" })).label).toBe("Failed · too_large");
    expect(badgeFor(row({ state: "deleted" })).label).toBe("Deleted");
    expect(badgeFor(row({ chunks: 0, embedded: 0 })).label).toBe("Searchable");
  });

  it("builds banners in words", () => {
    expect(bannersFor({ ...BASE, vault: { configured: false, readable: false } })).toEqual([
      "No vault configured. Set SB_VAULT_PATH to your Obsidian vault and restart the worker.",
    ]);
    expect(bannersFor({ ...BASE, vault: { configured: true, readable: false } })).toContain(
      "The vault folder can't be read. Nothing was deleted.",
    );
    const tripped = { ...BASE, last_run: { ...BASE.last_run!, outcome: "guard_tripped", counts: { tombstoned: 0, missing: 12 } } };
    expect(bannersFor(tripped)[0]).toMatch(/^The last scan found 12 notes missing and deleted nothing\./);
    expect(bannersFor({ ...BASE, embedding: { ...BASE.embedding, last_error: "embed_model_missing" } })).toContain(
      "The embedding model isn't installed. Run `ollama pull bge-m3` on the embedding host.",
    );
    expect(bannersFor({ ...BASE, embedding: { ...BASE.embedding, host_reachable: false } })).toContain(
      "The embedding host is unreachable. Notes stay searchable by text; vectors are added when it's back.",
    );
  });
});

describe("SourcesScreen", () => {
  function renderScreen(overrides: Partial<Parameters<typeof SourcesScreen>[0]> = {}) {
    const props = {
      summary: BASE,
      rows: [row({}), row({ path: "big.md", title: "big", state: "failed", error: "too_large", chunks: 0, embedded: 0 })],
      hasMore: false,
      scanPending: false,
      onRetry: vi.fn(async () => {}),
      onScan: vi.fn(async () => {}),
      onFilter: vi.fn(),
      onLoadMore: vi.fn(),
      ...overrides,
    };
    render(<SourcesScreen {...props} />);
    return props;
  }

  it("shows summary cards and the table", () => {
    renderScreen();
    expect(screen.getByText("Embedded 90%")).toBeInTheDocument();
    expect(screen.getByText("9 of 10 chunks")).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(table).getByText("Projects/NAS.md")).toBeInTheDocument();
    expect(within(table).getByText("Failed · too_large")).toBeInTheDocument();
  });

  it("retries failed rows and scans", async () => {
    const props = renderScreen();
    await userEvent.click(screen.getByRole("button", { name: "Retry big" }));
    expect(props.onRetry).toHaveBeenCalledOnce();
    await userEvent.click(screen.getByRole("button", { name: "Scan now" }));
    expect(props.onScan).toHaveBeenCalledOnce();
  });

  it("disables scanning while queued and filters by state", async () => {
    const props = renderScreen({ scanPending: true });
    expect(screen.getByRole("button", { name: "Scan queued…" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Failed" }));
    expect(props.onFilter).toHaveBeenCalledWith({ state: "failed", q: "" });
  });
});
```

Run: `pnpm exec vitest run src/features/sources`. Expected: FAIL (unresolved imports).

- [ ] **Step 3: Implement**

`web/src/features/sources/types.ts`:

```ts
import type { components } from "@/api/schema";

type S = components["schemas"];
export type SourcesSummary = S["SourcesSummary"];
export type SourceRow = S["SourceRow"];
export type SourceList = S["SourceList"];
export type StateFilter = "pending" | "indexed" | "failed" | "deleted" | null;
export type Filters = { state: StateFilter; q: string };
```

`web/src/features/sources/labels.ts`:

```ts
import type { SourceRow, SourcesSummary } from "./types";

export type Tone = "pending" | "searchable" | "failed" | "neutral";

export function badgeFor(row: SourceRow): { label: string; tone: Tone } {
  switch (row.state) {
    case "pending":
      return { label: "Waiting", tone: "pending" };
    case "failed":
      return { label: `Failed · ${row.error ?? "unknown"}`, tone: "failed" };
    case "deleted":
      return { label: "Deleted", tone: "neutral" };
    default:
      return row.embedded < row.chunks
        ? { label: "Text only", tone: "pending" }
        : { label: "Searchable", tone: "searchable" };
  }
}

export function bannersFor(summary: SourcesSummary): string[] {
  if (!summary.vault.configured) {
    return ["No vault configured. Set SB_VAULT_PATH to your Obsidian vault and restart the worker."];
  }
  const banners: string[] = [];
  const run = summary.last_run;
  if (!summary.vault.readable || run?.outcome === "vault_unavailable") {
    banners.push("The vault folder can't be read. Nothing was deleted.");
  }
  if (run?.outcome === "guard_tripped") {
    const missing = run.counts.missing ?? 0;
    banners.push(
      `The last scan found ${missing} notes missing and deleted nothing. Check the vault path, then run \`ai-second-brain vault reconcile --allow-mass-delete\`.`,
    );
  }
  if (summary.embedding.last_error === "embed_model_missing") {
    banners.push(`The embedding model isn't installed. Run \`ollama pull ${summary.embedding.model}\` on the embedding host.`);
  }
  if (summary.embedding.host_reachable === false) {
    banners.push("The embedding host is unreachable. Notes stay searchable by text; vectors are added when it's back.");
  }
  return banners;
}

export function relativeTime(iso: string, now: number = Date.now()): string {
  const seconds = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  return hours < 24 ? `${hours} h ago` : `${Math.round(hours / 24)} d ago`;
}
```

The guard banner reads `counts.missing`, which Task 8's reconcile records.

`web/src/features/sources/SourcesScreen.tsx`:

```tsx
import { RefreshCw } from "lucide-react";
import { useState } from "react";
import { cn } from "@/design-system/cn";
import { Button } from "@/design-system/ui/button";
import { badgeFor, bannersFor, relativeTime, type Tone } from "./labels";
import type { Filters, SourceRow, SourcesSummary, StateFilter } from "./types";

const TONES: Record<Tone, string> = {
  pending: "border-ingest-pending-border bg-ingest-pending-bg text-ingest-pending-fg",
  searchable: "border-ingest-searchable-border bg-ingest-searchable-bg text-ingest-searchable-fg",
  failed: "border-ingest-failed-border bg-ingest-failed-bg text-ingest-failed-fg",
  neutral: "border-border bg-surface text-fg-muted",
};
const FILTERS: { label: string; value: StateFilter }[] = [
  { label: "All", value: null }, { label: "Waiting", value: "pending" },
  { label: "Searchable", value: "indexed" }, { label: "Failed", value: "failed" }, { label: "Deleted", value: "deleted" },
];

type Props = {
  summary: SourcesSummary;
  rows: SourceRow[];
  hasMore: boolean;
  scanPending: boolean;
  onRetry: (row: SourceRow) => Promise<void>;
  onScan: () => Promise<void>;
  onFilter: (filters: Filters) => void;
  onLoadMore: () => void;
};

function Card({ title, value, detail }: { title: string; value: string; detail?: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface-raised p-4">
      <p className="text-sm text-fg-muted">{title}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
      {detail ? <p className="mt-1 text-xs text-fg-muted">{detail}</p> : null}
    </div>
  );
}

function canRetry(row: SourceRow): boolean {
  return row.state === "failed" || (row.state === "indexed" && row.embedded < row.chunks);
}

export function SourcesScreen({ summary, rows, hasMore, scanPending, onRetry, onScan, onFilter, onLoadMore }: Props) {
  const [filters, setFilters] = useState<Filters>({ state: null, q: "" });
  const { embedded, total } = summary.embedding;
  const pct = total === 0 ? 100 : Math.floor((embedded / total) * 100);
  const run = summary.last_run;
  const update = (next: Filters) => {
    setFilters(next);
    onFilter(next);
  };
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Sources</h1>
        <Button onClick={() => void onScan()} disabled={scanPending || !summary.vault.configured}>
          <RefreshCw aria-hidden /> {scanPending ? "Scan queued…" : "Scan now"}
        </Button>
      </div>
      {bannersFor(summary).map((text) => (
        <p key={text} role="status" className="rounded-md border border-warning-border bg-warning-bg px-3 py-2 text-sm text-warning-fg">
          {text}
        </p>
      ))}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Card title="Indexed" value={String(summary.revisions.indexed)} />
        <Card title="Waiting" value={String(summary.revisions.pending)} />
        <Card title="Failed" value={String(summary.revisions.failed)} />
        <Card title={`Embedded ${pct}%`} value={`${pct}%`} detail={`${embedded} of ${total} chunks`} />
        <Card
          title="Last scan"
          value={run ? relativeTime(run.started_at) : "never"}
          detail={run ? `${run.counts.changed ?? 0} changed` : undefined}
        />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => (
          <Button key={f.label} size="sm" variant={filters.state === f.value ? "primary" : "outline"} onClick={() => update({ ...filters, state: f.value })}>
            {f.label}
          </Button>
        ))}
        <label className="ml-auto flex items-center gap-2 text-sm">
          <span className="sr-only">Filter by title or path</span>
          <input
            className="h-8 rounded-md border border-border-input bg-surface-raised px-2"
            placeholder="Filter by title or path"
            value={filters.q}
            onChange={(e) => update({ ...filters, q: e.target.value })}
          />
        </label>
      </div>
      <table className="w-full text-sm">
        <thead className="text-left text-fg-muted">
          <tr><th className="py-2">Title</th><th>Path</th><th>Status</th><th>Vectors</th><th>Indexed</th><th /></tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const badge = badgeFor(r);
            return (
              <tr key={r.id} className="border-t border-border align-top">
                <td className="py-2 pr-2">{r.title ?? r.path}</td>
                <td className="pr-2 font-mono break-all">{r.path}</td>
                <td className="pr-2"><span className={cn("inline-block rounded-md border px-2 py-0.5 text-xs", TONES[badge.tone])}>{badge.label}</span></td>
                <td className="pr-2">{`Embedded ${r.embedded}/${r.chunks}`}</td>
                <td className="pr-2">{r.indexed_at ? relativeTime(r.indexed_at) : "—"}</td>
                <td>{canRetry(r) ? <Button size="sm" variant="outline" aria-label={`Retry ${r.title ?? r.path}`} onClick={() => void onRetry(r)}>Retry</Button> : null}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {hasMore ? <Button variant="outline" onClick={onLoadMore}>Load more</Button> : null}
    </div>
  );
}
```

Under 768 px, the table collapses by wrapping each `tr` as a block. Add the utility classes `max-md:block` to `table`, `thead` (`max-md:hidden`), `tr` (`max-md:block max-md:py-2`) and `td` (`max-md:block`); these are token-free utilities.

`web/src/features/sources/api.ts`:

```ts
import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { Filters } from "./types";

export const sourcesKeys = { summary: ["sources", "summary"] as const, list: (f: Filters) => ["sources", "list", f] as const };

export const summaryQueryOptions = queryOptions({
  queryKey: sourcesKeys.summary,
  queryFn: async () => {
    const { data, response } = await api.GET("/api/sources/summary");
    if (!data) throw new Error(`Sources summary failed with status ${response.status}`);
    return data;
  },
  refetchInterval: (query) => (query.state.data && query.state.data.revisions.pending > 0 ? 10_000 : 60_000),
});

export function listQueryOptions(filters: Filters) {
  return infiniteQueryOptions({
    queryKey: sourcesKeys.list(filters),
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) => {
      const query: { state?: NonNullable<Filters["state"]>; q?: string; cursor?: string } = {};
      if (filters.state) query.state = filters.state;
      if (filters.q) query.q = filters.q;
      if (pageParam) query.cursor = pageParam;
      const { data, response } = await api.GET("/api/sources", { params: { query } });
      if (!data) throw new Error(`Sources list failed with status ${response.status}`);
      return data;
    },
    getNextPageParam: (last) => last.next_cursor,
  });
}

export async function retrySource(id: string): Promise<boolean> {
  const { response } = await api.POST("/api/sources/{source_id}/retry", { params: { path: { source_id: id } } });
  return response.status === 202;
}

export async function reconcileVault(): Promise<boolean> {
  const { response } = await api.POST("/api/sources/reconcile");
  return response.status === 202;
}
```

`web/src/routes/_app/sources.tsx`:

```tsx
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { listQueryOptions, reconcileVault, retrySource, sourcesKeys, summaryQueryOptions } from "@/features/sources/api";
import { SourcesScreen } from "@/features/sources/SourcesScreen";
import type { Filters } from "@/features/sources/types";

export const Route = createFileRoute("/_app/sources")({ component: SourcesRoute });

function SourcesRoute() {
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<Filters>({ state: null, q: "" });
  const [debounced, setDebounced] = useState(filters);
  const [scanPending, setScanPending] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(filters), 300);
    return () => clearTimeout(t);
  }, [filters]);
  const summary = useQuery(summaryQueryOptions);
  const list = useInfiniteQuery(listQueryOptions(debounced));
  useEffect(() => {
    if (scanPending && summary.data?.last_run?.trigger === "manual" && summary.data.last_run.finished_at) setScanPending(false);
  }, [scanPending, summary.data]);

  if (summary.isPending) return <p className="text-sm text-fg-muted">Loading…</p>;
  if (summary.isError) return <p role="alert" className="text-sm text-danger-fg">Couldn't load sources.</p>;
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["sources"] });
  return (
    <SourcesScreen
      summary={summary.data}
      rows={list.data?.pages.flatMap((p) => p.items) ?? []}
      hasMore={list.hasNextPage}
      scanPending={scanPending}
      onRetry={async (row) => {
        await retrySource(row.id);
        await refresh();
      }}
      onScan={async () => {
        if (await reconcileVault()) setScanPending(true);
        await queryClient.invalidateQueries({ queryKey: sourcesKeys.summary });
      }}
      onFilter={setFilters}
      onLoadMore={() => void list.fetchNextPage()}
    />
  );
}
```

- [ ] **Step 4: Verify and commit (no push)**

Run: `pnpm exec tsr generate`, `pnpm exec vitest run`, and `just web::check` from the repo root. Expected: pass, clean.

```bash
git add web/src
git commit -m "feat(web): add the Sources screen"
```

---

### Task 12: End-to-end: fixture vault, worker and Sources

**Files:**
- Create: `web/tests/e2e/fixtures/vault/` (6 notes), `web/tests/e2e/sources.spec.ts`, `backend/tests/e2e_reset.py`
- Modify: `web/tests/e2e/fixtures/fake-ollama.ts` (the `/api/embed` route), `web/playwright.config.ts` (a worker web server, `SB_VAULT_PATH`, `SB_EMBED_URL`)

**Interfaces:**
- Consumes: everything above.
- Produces: an e2e check that the whole pipeline works in a real browser.

- [ ] **Step 1: Fixture vault**

Create these files under `web/tests/e2e/fixtures/vault/`:

| File | Content |
|---|---|
| `Projects/NAS.md` | `---\ntags: [homelab]\n---\n# NAS\n## Dyski\nCztery dyski w RAID 5.\n## Kopie zapasowe\nCo noc o 02:00 na zewnętrzny dysk.\n` |
| `Projects/Proxmox.md` | `# Proxmox\nKlaster z jednym węzłem. Zobacz [[NAS]].\n` |
| `Ideas/Second brain.md` | `# Second brain\nPrivate by default. Local models only.\n` |
| `Journal/2026-09-30.md` | `Dzisiaj: indeksowanie notatek.\n` |
| `Reading/Designing Data-Intensive Applications.md` | `# DDIA\n## Replication\nLeader-based replication notes.\n` |
| `.obsidian/workspace.md` | `ignored` |

- [ ] **Step 2: Fake embed endpoint**

In `web/tests/e2e/fixtures/fake-ollama.ts`, before the 404 fallback, add:

```ts
  if (path === "/api/embed" && req.method === "POST") {
    const body = JSON.parse(await readBody(req)) as { input: string[] | string };
    const inputs = Array.isArray(body.input) ? body.input : [body.input];
    const embeddings = inputs.map((text) => {
      let seed = 0;
      for (const ch of text) seed = (seed * 31 + ch.codePointAt(0)!) >>> 0;
      const v = Array.from({ length: 1024 }, (_, i) => Math.sin(seed + i));
      const norm = Math.hypot(...v) || 1;
      return v.map((x) => x / norm);
    });
    json(res, 200, { embeddings });
    return;
  }
```

- [ ] **Step 3: Playwright config**

In `web/playwright.config.ts`:
- Compute `const fixtureVault = join(root, "web", "tests", "e2e", "fixtures", "vault");`.
- Add to `serverEnv`: `SB_VAULT_PATH: fixtureVault`, `SB_EMBED_URL: fakeOllamaURL`, `SB_RECONCILE_MINUTES: "60"`.
- The e2e test database must start without leftover sources, so the worker's startup reconcile indexes exactly the fixture vault. Add a small reset script `backend/tests/e2e_reset.py`:

```python
"""Empty the ingestion tables of the e2e database (run just before the e2e worker starts)."""

import os

import psycopg

with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
    conn.execute("TRUNCATE sources, ingest_runs, procrastinate_jobs CASCADE")
```

- Add a web server entry after the API. The reset runs first in the same command, so it always happens before the worker's startup reconcile. (Playwright starts web servers before any `globalSetup`, so a global setup would be too late.)

```ts
    {
      command: "uv run --directory ../backend python tests/e2e_reset.py && uv run --directory ../backend ai-second-brain worker",
      url: `http://127.0.0.1:${apiPort}/api/health`,
      env: serverEnv,
      reuseExistingServer: false,
      timeout: 60_000,
      gracefulShutdown: { signal: "SIGTERM", timeout: 10000 },
    },
```

  `serverEnv.DATABASE_URL` is already the test database. The worker has no HTTP port, so this entry waits on the API's health URL; Playwright only needs the process started. `&&` works in both `cmd.exe` (which Playwright uses on Windows) and `sh`.

- [ ] **Step 4: Spec**

`web/tests/e2e/sources.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

const PASSWORD = "e2e-test-password";

test("the worker indexes the fixture vault and Sources shows it", async ({ page }) => {
  await page.goto("/sources");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/sources$/);
  const table = page.getByRole("table");
  await expect(table.getByText("Projects/NAS.md")).toBeVisible({ timeout: 30_000 });
  await expect(table.getByText("Searchable")).toHaveCount(5, { timeout: 60_000 });
  await expect(table.getByText(".obsidian/workspace.md")).toHaveCount(0);
  await expect(page.getByText("Embedded 100%")).toBeVisible();
  await page.getByRole("button", { name: "Scan now" }).click();
  await expect(page.getByRole("button", { name: "Scan queued…" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Scan now" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("just now")).toBeVisible();
});
```

- [ ] **Step 5: Verify and commit (no push)**

Run: `just e2e` twice. Expected: all e2e specs pass, including the existing chat and auth specs. If the worker web-server entry stops the stack from exiting cleanly on Windows, report it with details. Don't add sleeps.

```bash
git add web/tests/e2e web/playwright.config.ts backend/tests/e2e_reset.py
git commit -m "test(e2e): index a fixture vault through the worker"
```

---

### Task 13: Docs, ADRs, screenshot and final checks

**Files:**
- Modify: `README.md`, `docs/architecture/adr/0003-postgres-job-queue.md`, `docs/architecture/adr/0006-embedding-spaces.md`, `docs/architecture/system-design.md` §9
- Create: `docs/images/readme/sources.jpg`, `web/tests/e2e/readme-screenshots.spec.ts` (add a second test)

**Interfaces:** none. This task is documentation only.

- [ ] **Step 1: Screenshot**

Append to `web/tests/e2e/readme-screenshots.spec.ts` (keep it opt-in with `README_SHOTS`):

```ts
test("sources screen", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/sources");
  await page.getByLabel("Password").fill("e2e-test-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("table").getByText("Searchable")).toHaveCount(5, { timeout: 60_000 });
  await page.screenshot({ path: "../docs/images/readme/sources.jpg", type: "jpeg", quality: 85 });
});
```

Run it with `README_SHOTS=1` (PowerShell: `$env:README_SHOTS='1'; pnpm exec playwright test readme-screenshots`). Open `docs/images/readme/sources.jpg` and check it: five fixture notes, all "Searchable", "Embedded 100%".

- [ ] **Step 2: README**

Update `README.md` in place, matching its existing voice and structure:
- **"What it does today":** a bullet about vault ingestion: "the worker keeps an index of your Obsidian vault in Postgres (full-text immediately, bge-m3 vectors in the background), survives crashes and offline edits, and shows its state on the Sources screen. Search and using your notes in chat arrive in Phase 2b."
- **Screenshots:** add `sources.jpg` after `ask.jpg`.
- **Roadmap:** split Phase 2 into 2a (✅) and 2b, and narrow Phase 3 to the evaluation.
- **Everyday commands:** `just worker`, `just vault-scan`, `just vault-status`; note that `just dev` now starts the worker too.
- **Configuration → a "Vault ingestion" subsection:**
  - the spec §9 steps;
  - a settings table with the seven variables and their defaults;
  - the mass-deletion guard (what trips it, and that only the CLI overrides it);
  - one worker per deployment;
  - network shares and WSL paths.
- **Troubleshooting:**
  - "The embedding model isn't installed": `ollama pull bge-m3` on the embedding host; embedding resumes by itself;
  - "found N notes missing and deleted nothing": check `SB_VAULT_PATH`, then `just vault-scan --allow-mass-delete`.
- **Repository layout:** add `backend/src/ai_second_brain/vault/`, `knowledge/`, `ingest/` and `web/src/features/sources/`.

- [ ] **Step 3: ADRs and system design**

- **ADR-0003:** set `**Status:** Accepted (2026-09-30)`. Add a "Implementation notes (Phase 2a)" section covering:
  - the vendored schema migration;
  - queueing after commit, with reconcile recovery;
  - heartbeat-based stalled jobs;
  - the reconcile timer inside the worker;
  - the queues `ingest` and `embed`.
- **ADR-0006:** set `**Status:** Accepted (2026-09-30)`. Add a note: "Space 1 is bge-m3 (1024-d) from Phase 2a; the bake-off against MiniLM/e5 moves to Phase 3 as an evaluation of this default."
- **`system-design.md` §9:** replace the Phase 2 row with two rows. 2a is "Durable vault ingestion" — **delivered** ([spec](../superpowers/specs/2026-09-30-phase-2a-vault-ingestion-design.md)). 2b is "Search + chat retrieval + capture", covering the hybrid FTS + vector search API and page, the real Retriever in private chat, and the capture box. Change Phase 3 to "Embedding evaluation (bake-off vs bge-m3; add a space only if it wins)".

- [ ] **Step 4: Final verification**

Run from the repository root: `just check`, `just test`, `just e2e`. Expected: all pass. Owner step (not CI): `just dev` against the real vault.

- [ ] **Step 5: Commit (no push)**

```bash
git add README.md docs web/tests/e2e/readme-screenshots.spec.ts
git commit -m "docs: document vault ingestion and the worker"
```

The single end-of-phase push happens after the final whole-branch review and its fixes (owner decision). CI then releases v0.4.0.

# Phase 2a: durable vault ingestion

Date: 2026-09-30 · Status: **approved design, spec under review** · Owner: Michal Dyzma
Parent docs: [system design](../../architecture/system-design.md) §3.1, §4.1, §9 · ADRs [0003](../../architecture/adr/0003-postgres-job-queue.md), [0006](../../architecture/adr/0006-embedding-spaces.md) · [design system](../../architecture/design-system-audit.md) §3.2 (`IngestStatus`, `SystemBanner`) · builds on [Phase 1b](2026-09-29-phase-1b-private-chat-design.md)

## 1. Purpose and success

Make the owner's Obsidian vault a durable, always-current index in PostgreSQL: every note is parsed into chunks that are full-text searchable at once and gain local bge-m3 vectors shortly after. Nothing is lost on crashes, restarts, Ollama outages or offline edits. Phase 2 is split: **2a (this spec)** builds ingestion and its status screen. **2b** adds the search API and page, retrieval in private chat, and the capture box.

**Success (exit criteria):**
1. With `SB_VAULT_PATH` set and `just dev` running (API + web + worker), every `*.md` note in the vault reaches `indexed` with complete vectors in the default space. The Sources screen shows this.
2. Editing, creating, deleting or renaming a note in Obsidian changes its indexed state within seconds (watcher), and within `SB_RECONCILE_MINUTES` even if events are missed (reconcile).
3. The crash, retry and delete integration tests in §10 pass: crash mid-index, crash between embedding batches, Ollama down and back, delete/restore/move, offline changes, the mass-deletion guard.
4. CI: Linux full suite plus e2e; macOS checks plus unit tests. CI releases v0.4.0.

## 2. Scope

**In:** knowledge schema (sources, revisions, chunks, embedding spaces, embeddings, ingest runs); procrastinate job queue; `ai-second-brain worker` (job worker + file watcher + scheduled reconcile); observe → index → embed pipeline; Obsidian parsing and heading-aware chunking; moves, tombstones, the mass-deletion guard; Sources API and screen; `vault reconcile` / `vault status` CLI; fake Ollama `/api/embed`; docs.

**Out:** search API and page, retrieval in chat, capture box (2b); PDF, email, git and other sources (Phase 6); entities, edges and salience (Phases 4 and 7); several vaults; attachments; editing notes in the app; a purge / hard-delete screen; the embedding evaluation and model switching (Phase 3); cloud embeddings (never).

## 3. Settings

New `Settings` fields (`SB_` prefix, environment and `.env`; `env_ignore_empty` already applies):

| Variable | Type / default | Rules |
|---|---|---|
| `SB_VAULT_PATH` | path, default empty | Empty → ingestion disabled (the worker idles and Sources says so). Otherwise it must be an absolute path; readability is checked at worker start and on every reconcile, not at API start. |
| `SB_VAULT_EXCLUDE` | comma-separated glob list, default `.obsidian/**,.trash/**,**/.git/**` | Matched against vault-relative POSIX paths. Only `*.md` files are ever considered. |
| `SB_EMBED_URL` | URL, default empty | Empty → the first `SB_OLLAMA_ENDPOINTS` URL. If both are empty, embedding is unavailable: notes are still indexed for full text and Sources shows the embedding warning. The same URL rules as chat endpoints apply (http/https, host, no user info, query or fragment). |
| `SB_EMBED_MODEL` | str, default `bge-m3` | Must equal the `model` of the default `embedding_spaces` row; a mismatch is a worker startup error naming both values. |
| `SB_EMBED_BATCH` | int, default 16, 1–128 | Chunks per `/api/embed` call. |
| `SB_RECONCILE_MINUTES` | int, default 15, 1–1440 | Scheduled reconcile interval. |
| `SB_MAX_NOTE_BYTES` | int, default 2 000 000, 1 000–50 000 000 | Larger files are not read. |

The embedding HTTP client follows the 1b transport rules: `httpx2.AsyncClient(follow_redirects=False, trust_env=False)`, 5 s connect, 120 s read, no cloud fallback.

## 4. Database

### 4.1 Knowledge migration (`db/migrations/<ts>_knowledge.sql`)

```sql
-- migrate:up
CREATE TYPE sensitivity   AS ENUM ('private', 'shareable');
CREATE TYPE ingest_state  AS ENUM ('pending', 'indexed', 'failed', 'superseded');
CREATE TYPE salience_tier AS ENUM ('active', 'dormant', 'superseded', 'archived');
CREATE TYPE source_kind   AS ENUM ('obsidian');

CREATE TABLE sources (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind                source_kind NOT NULL,
    external_ref        text NOT NULL,              -- vault-relative POSIX path, e.g. 'Projects/NAS.md'
    title               text,
    sensitivity         sensitivity NOT NULL DEFAULT 'private',
    salience            salience_tier NOT NULL DEFAULT 'active',
    current_revision_id uuid,
    created_at          timestamptz NOT NULL DEFAULT now(),
    deleted_at          timestamptz,                -- tombstone
    UNIQUE (kind, external_ref)
);

CREATE TABLE source_revisions (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id    uuid NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    content_hash bytea NOT NULL,                    -- sha256 of normalized text (or of the size/mtime marker, §5.1)
    raw_text     text NOT NULL,
    metadata     jsonb NOT NULL DEFAULT '{}',       -- frontmatter, links, size, mtime_ns, frontmatter_error
    state        ingest_state NOT NULL DEFAULT 'pending',
    error        text,                              -- error code only (§5.6), never content
    observed_at  timestamptz NOT NULL DEFAULT now(),
    indexed_at   timestamptz,
    UNIQUE (source_id, content_hash)
);
CREATE INDEX source_revisions_pending_idx ON source_revisions (source_id, observed_at) WHERE state = 'pending';
ALTER TABLE sources ADD CONSTRAINT sources_current_revision_fk
    FOREIGN KEY (current_revision_id) REFERENCES source_revisions(id);

CREATE TABLE chunks (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    revision_id  uuid NOT NULL REFERENCES source_revisions(id) ON DELETE CASCADE,
    ordinal      int  NOT NULL CHECK (ordinal >= 0),
    heading_path text[] NOT NULL DEFAULT '{}',
    content      text NOT NULL,
    tsv          tsvector GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED,
    UNIQUE (revision_id, ordinal)
);
CREATE INDEX chunks_tsv_gin ON chunks USING gin (tsv);

CREATE TABLE embedding_spaces (
    id         smallint PRIMARY KEY,
    model      text NOT NULL UNIQUE,
    dims       int  NOT NULL CHECK (dims > 0),
    is_default boolean NOT NULL DEFAULT false
);
CREATE UNIQUE INDEX embedding_spaces_one_default ON embedding_spaces (is_default) WHERE is_default;
INSERT INTO embedding_spaces (id, model, dims, is_default) VALUES (1, 'bge-m3', 1024, true);

CREATE TABLE chunk_embeddings (
    chunk_id  uuid NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    space_id  smallint NOT NULL REFERENCES embedding_spaces(id),
    embedding halfvec NOT NULL,
    PRIMARY KEY (chunk_id, space_id)
);
CREATE INDEX chunk_emb_s1_hnsw ON chunk_embeddings
    USING hnsw ((embedding::halfvec(1024)) halfvec_cosine_ops) WHERE space_id = 1;

CREATE TABLE ingest_runs (
    id          bigserial PRIMARY KEY,
    trigger     text NOT NULL CHECK (trigger IN ('startup', 'schedule', 'manual', 'cli')),
    started_at  timestamptz NOT NULL,
    finished_at timestamptz,
    outcome     text,                               -- 'ok' | 'guard_tripped' | 'vault_unavailable' | 'disabled' | 'error:<code>'
    counts      jsonb NOT NULL DEFAULT '{}'         -- seen, new, changed, moved, tombstoned, requeued_index, requeued_embed, stalled_reset
);

-- migrate:down
DROP TABLE ingest_runs;
DROP TABLE chunk_embeddings;
DROP TABLE embedding_spaces;
DROP TABLE chunks;
ALTER TABLE sources DROP CONSTRAINT sources_current_revision_fk;
DROP TABLE source_revisions;
DROP TABLE sources;
DROP TYPE source_kind;
DROP TYPE salience_tier;
DROP TYPE ingest_state;
DROP TYPE sensitivity;
```

- **Superseded revisions** keep their row; their chunks (and so their embeddings) are deleted at swap time, so old text is never searchable.
- **Deletion** sets `deleted_at` and deletes the current revision's chunks. Source and revision rows stay, so a restored file reconnects to its history.
- **Source identity:** a source is identified by `(kind, external_ref)`. A move updates `external_ref` in place (§5.5).

### 4.2 Procrastinate migration (`db/migrations/<ts>_procrastinate.sql`)

- The pinned procrastinate version's schema SQL, generated with its own schema command and committed as a dbmate migration. dbmate stays the only schema tool, and procrastinate's automatic schema apply is never used.
- A `down` section drops procrastinate's tables, types and functions.
- Upgrading procrastinate means a new migration, with procrastinate's published migration SQL for that version. A test pins the expectation (§10.3 #11).
- Queues are `ingest` and `embed`. **Job arguments carry ids only, never note text or paths** (ADR-0003).

## 5. Pipeline (`backend/src/ai_second_brain/vault/`, `knowledge/`)

### 5.1 Observe (`vault/observe.py`)

`observe(rel_path)` is called by the watcher, reconcile and the CLI. `rel_path` is a vault-relative POSIX path:

1. **Size check:** `stat` the file. If `size > SB_MAX_NOTE_BYTES`, the revision is a `failed` revision with `error='too_large'`, `raw_text=''` and `content_hash = sha256(f"too_large:{size}:{mtime_ns}")`. The file is not read.
2. **Read and decode:** read the bytes and decode as UTF-8, removing a leading BOM. Invalid UTF-8 → a `failed` revision, `error='encoding'`, hash of the raw bytes, `raw_text=''`.
3. **Normalize:** `\r\n` and `\r` become `\n`, then Unicode NFC. `content_hash = sha256(normalized.encode())`.
4. **Record, in one transaction:**
   - Upsert the source by `(kind='obsidian', external_ref=rel_path)`, clearing `deleted_at` if set.
   - Insert the revision (state `pending`, metadata `{size, mtime_ns}`) with `ON CONFLICT (source_id, content_hash)`:
     - **no conflict:** it's new → queue indexing;
     - **conflict, and it's the current `indexed` revision whose chunks exist:** no-op, apart from refreshing `metadata.size/mtime_ns`;
     - **conflict, and it's the current revision of a source that was tombstoned** (chunks deleted): set it `pending` → queue indexing;
     - **conflict with a non-current revision** (a revert): set it `pending`, update `observed_at` → queue indexing.
   - Queue `index_source(source_id)` on queue `ingest` with `queueing_lock = f"index:{source_id}"`. If a job with that lock is already waiting, nothing more is queued, because the waiting job will take the newest pending revision.
5. **Errors:** an `OSError` while reading gives `error='io_error'` and no revision is written. Reconcile retries on its next pass, and the error is counted in the run.

### 5.2 Parse (`vault/parse.py`, pure)

- **Frontmatter:** a leading `---\n…\n---` block goes through `yaml.safe_load`. The resulting dict goes to `metadata.frontmatter`. Anything that isn't a dict, or invalid YAML, leaves the block in the body with `metadata.frontmatter_error = true`.
- **Title:** frontmatter `title` (if a non-empty string), otherwise the first ATX `# ` heading outside code, otherwise the file stem.
- **Links:** `[[target]]`, `[[target|alias]]` and `[[target#heading]]` targets outside code → `metadata.links` (deduplicated, in order). They aren't used in 2a.

### 5.3 Chunk (`vault/chunk.py`, pure)

- **Sections:** the body splits at ATX headings (`#`–`######`), ignoring lines inside fenced code blocks (``` and ~~~). Each section carries `heading_path`, the chain of enclosing heading texts. Text before the first heading has an empty path.
- **Size limits** (in characters of the section body; the heading line itself isn't repeated in the content):
  - a section of ≤ 1600 characters is one chunk;
  - a longer one is split at blank-line paragraph boundaries into chunks of ≤ 1600 characters, each starting with the last ≤ 200 characters of the previous chunk (snapped forward to a word boundary) as overlap;
  - a single paragraph over 1600 characters is split at sentence ends (`. ! ?` followed by whitespace), then hard-split at 1600 characters if needed.
- **Dropped:** sections whose body is empty or whitespace. A note with no body at all has zero chunks and is still `indexed`.
- **Ordering:** `ordinal` is 0-based over the whole note, in document order.

### 5.4 Index (`knowledge/index.py`, job `index_source(source_id)`)

1. Lock the source row (`FOR UPDATE`). Pick its newest `pending` revision by `observed_at`. None → return. Older `pending` revisions of the source become `superseded`.
2. Parse and chunk `raw_text`.
3. **In the same transaction:**
   - insert the chunks;
   - delete the chunks of the previous current revision (if different) and set it `superseded`;
   - set the new revision `indexed` with `indexed_at=now()` and `error=NULL`;
   - update the source's `current_revision_id` and `title`;
   - queue `embed_revision(revision_id, space_id=<default>)` on queue `embed` with `queueing_lock = f"embed:{revision_id}"`.
4. **Failure:** an exception rolls the transaction back and the revision stays `pending`. procrastinate retries 3 times (10 s, 30 s, 90 s). After the last attempt, a separate transaction sets it `failed` with `error='index_error'`. Parse and chunk are pure and total, so this means a database or programming fault.

### 5.5 Moves and deletions

- **Tombstone (`vault/tombstone.py`):** set `deleted_at=now()` and delete the current revision's chunks, in one transaction.
- **Move pairing** (`vault/moves.py`, pure): given a set of deleted paths and a set of added paths within one watcher batch, or within one reconcile pass, a deleted path whose source's current `content_hash` equals the added file's hash forms a pair.
  - Each pair updates that source's `external_ref` to the new path and clears `deleted_at` if it was set. There's no new revision and no re-index. If the hash matches several deleted paths, the one sharing the most leading path segments wins, then the lexically first.
  - Unpaired deletes are tombstoned; unpaired adds are observed.
  - **Known limitation:** a move whose delete and create land in different batches becomes a new source plus a tombstoned old one. Search results are still correct, but the old source's history isn't linked.

### 5.6 Embed (`knowledge/embed.py`, job `embed_revision(revision_id, space_id)`)

1. **Skip if stale:** if the revision is not its source's current revision, or the source is tombstoned → return.
2. **Batching:** load the revision's chunks that have no row for `space_id` in `chunk_embeddings`, ordered by `ordinal`. In batches of `SB_EMBED_BATCH`, call `POST {embed_url}/api/embed` with `{"model": <space.model>, "input": [<embed_text>…]}`. Here `embed_text = f"{title} › {' › '.join(heading_path)}\n\n{content}"`, with the ` › …` part left out when `heading_path` is empty.
3. **Validation:** the response must be 200 JSON with `embeddings` as a list of exactly one vector per input, each vector a list of `space.dims` finite numbers. Each batch's rows are written in its own transaction.
4. **Error codes and retries:**

| Condition | Code | Behaviour |
|---|---|---|
| Connection refused, timeout, 5xx | `embed_unreachable` | Retried by procrastinate: 8 attempts, exponential from 30 s, capped at 1 h. Afterwards the job ends; reconcile re-queues (§6.3). |
| 404 whose body mentions the model | `embed_model_missing` | No retry. Recorded for Sources (§7.1) until a later embed succeeds. |
| Malformed JSON, wrong count or size, non-finite values, redirect | `embed_bad_response` | No retry. Recorded for Sources. |

   The last embedding error per revision is kept in `source_revisions.metadata.embed_error` (a code) and cleared when a later embed of that revision completes. A revision is **fully embedded** when every chunk has a row for the default space.

### 5.7 Error codes (the complete set stored or shown)

`too_large`, `encoding`, `io_error` (counted, not stored), `index_error`, `embed_unreachable`, `embed_model_missing`, `embed_bad_response`. Reconcile outcomes: `ok`, `guard_tripped`, `vault_unavailable`, `disabled`, `error:<code>`.

## 6. Worker (`interfaces/cli` → `ai-second-brain worker`)

### 6.1 Process

- One asyncio process on the selector event loop (`ai_second_brain.runtime.new_event_loop`), running three parts:
  1. **The procrastinate worker** for queues `ingest` and `embed`, concurrency 2.
  2. **The watcher task.**
  3. **The scheduled reconcile:** a procrastinate periodic task every `SB_RECONCILE_MINUTES`, plus one reconcile at startup with `trigger='startup'`.
- **Startup checks:** database reachable (retry with backoff, logging `database_unavailable`); `SB_EMBED_MODEL` equals the default space's model (else exit 1 with a message naming both); vault configured (else idle, recording one `ingest_runs` row with `outcome='disabled'` at startup).
- **Shutdown:** SIGINT/SIGTERM (Ctrl+C on Windows) stops the watcher, asks procrastinate to finish the current jobs (up to 30 s), then exits 0.
- **One worker per deployment.** A second worker is safe (locks, idempotent observe) but wasteful. The README says to run one.

### 6.2 Watcher (`vault/watcher.py`)

- `watchfiles.awatch(vault_path, recursive=True)` with the default debounce, filtered to paths ending `.md` (case-insensitive) that aren't excluded.
- Each batch: map changes to vault-relative POSIX paths; for deleted paths, look up their sources; for added and modified paths, hash the files; apply move pairing (§5.5); then observe or tombstone.
- If the watcher raises (vault vanished, permissions), log `watcher_error` with the exception type only, wait with exponential backoff (1 s → 60 s), and restart. Reconcile is the safety net.

### 6.3 Reconcile (`vault/reconcile.py`)

One pass, recorded as an `ingest_runs` row:
1. **Vault check:** if the vault path is missing or unreadable, `outcome='vault_unavailable'` and stop, with no tombstones.
2. **Walk:** walk the vault (`os.scandir`, recursive, not following symlinks, applying exclusions). For each `.md` file compare `(size, mtime_ns)` with the current revision's `metadata`. New or different → observe (`new` or `changed` count).
3. **Missing files:** live sources with no matching file on disk → run move pairing against this pass's new files, then:
   - **Mass-deletion guard:** if the number to tombstone is greater than 10 **and** greater than 20% of live sources, tombstone nothing and set `outcome='guard_tripped'` (the counts record how many were missing).
   - Otherwise tombstone them.
4. **Recovery:**
   - re-queue `index_source` for sources with a `pending` revision and no waiting or running job;
   - re-queue `embed_revision` for current, non-tombstoned revisions that are not fully embedded and have no waiting or running job, unless their `metadata.embed_error` is `embed_bad_response` (that one needs Retry from Sources). `embed_model_missing` is re-queued, so pulling the model resumes embedding by itself; the failing call is a cheap 404;
   - reset procrastinate jobs in `doing` for longer than 10 minutes to be retried (procrastinate's stalled-job API).
5. `outcome='ok'`.
6. **Overriding the guard:** `vault reconcile --allow-mass-delete` runs one pass with the guard disabled. The API cannot override the guard.

## 7. API and web

### 7.1 API (all require a session; POSTs pass the same-origin guard; errors use the 1a `{"detail": code}` format)

| Method & path | Response |
|---|---|
| `GET /api/sources/summary` | See the object after this table. |
| `GET /api/sources?state=&q=&cursor=` | `{items: SourceRow[], next_cursor: str\|null}`, 50 per page, ordered by `external_ref`. `state` is one of `indexed`/`pending`/`failed`/`deleted` (a source's state is its newest revision's state, or `deleted` if tombstoned). `q` is a case-insensitive substring of the title or path. The cursor is opaque. |
| `POST /api/sources/{id}/retry` | `202`. Re-queues `index_source` if the newest revision is `failed` (resetting it to `pending`), or `embed_revision` if the current revision isn't fully embedded (clearing `embed_error`). `409 nothing_to_retry` otherwise; `404 not_found`. |
| `POST /api/sources/reconcile` | `202 {run_id}`. Queues a reconcile with `trigger='manual'` (no guard override). `409 vault_disabled` if no vault is configured. |

The summary object:

```text
{vault: {configured, readable},
 sources: {active, deleted},
 revisions: {pending, indexed, failed},
 chunks,
 embedding: {model, embedded, total, host_reachable, last_error},
 jobs: {waiting, failed},
 last_run: {trigger, started_at, finished_at, outcome, counts} | null}
```

- `host_reachable` is a 1 s probe of `{embed_url}/api/version`, cached 10 s.
- `last_error` is the most common `embed_error` among revisions that aren't fully embedded, or null.

`SourceRow = {id, title, path, state, error, indexed_at, chunks, embedded}`. Paths and titles appear only in authenticated responses and are never logged.

### 7.2 Web: the Sources screen (`/sources`, replacing the placeholder)

- **Summary cards:** "Indexed", "Waiting", "Failed", "Embedded {pct}%" (with "{embedded} of {total} chunks"), and "Last scan {relative time} · {changed} changed".
- **Warnings** (`SystemBanner` variants; text carries the meaning):

| Condition | Text |
|---|---|
| Vault not configured | "No vault configured. Set SB_VAULT_PATH to your Obsidian vault and restart the worker." |
| `vault_unavailable` | "The vault folder can't be read. Nothing was deleted." |
| `guard_tripped` | "The last scan found {n} notes missing and deleted nothing. Check the vault path, then run `ai-second-brain vault reconcile --allow-mass-delete`." |
| `embed_model_missing` | "The embedding model isn't installed. Run `ollama pull {model}` on the embedding host." |
| Host unreachable | "The embedding host is unreachable. Notes stay searchable by text; vectors are added when it's back." |

- **Table** (cards below 768 px): title; path (monospace); `IngestStatus` badge (`pending` → "Waiting", `indexed` and fully embedded → "Searchable", `indexed` but not fully embedded → "Text only", `failed` → "Failed · {code}", `deleted` → "Deleted"); "Embedded {embedded}/{chunks}"; indexed time; a **Retry** button on rows where retry applies.
- **Filters:** state chips and a text filter (debounced 300 ms) mapped to `state`/`q`, plus a "Load more" button.
- **Scan now** triggers `POST /api/sources/reconcile`. It's disabled while a manual run is queued or running and shows "Scan queued…".
- **Refresh:** every 10 s while `revisions.pending > 0` or a manual run is in progress, otherwise every 60 s.
- **Tokens:** the existing `ingest-pending/searchable/failed` tokens, mapped into `@theme inline` like the tier tokens.

### 7.3 CLI and `just`

| Command | Recipe | Does |
|---|---|---|
| `ai-second-brain worker` | `just worker` | §6. |
| `ai-second-brain vault reconcile [--allow-mass-delete]` | `just vault-scan` | One reconcile pass in this process (`trigger='cli'`). Prints the counts and outcome; exits 1 on `vault_unavailable`/`guard_tripped`/error. Jobs it queues run in the worker. |
| `ai-second-brain vault status` | `just vault-status` | Prints the §7.1 summary as text. |

`just dev` runs the API, the web app and the worker through `concurrently` (three named processes).

## 8. Privacy and logging

- Log lines from ingestion carry: job name, source id or revision id, counts, durations, outcome and error codes. **No note text, titles or paths** (a file name can itself be private).
- Job arguments: ids only.
- The `error` column and `embed_error` hold codes only.
- The embedding host is the configured local Ollama. Nothing is sent to any cloud service.

## 9. Operator setup (README)

1. Set `SB_VAULT_PATH` (and, if needed, `SB_VAULT_EXCLUDE`) in `.env`.
2. On the embedding host: `ollama pull bge-m3`. Set `SB_EMBED_URL` if embedding runs on a different host from chat.
3. `just db::migrate` (new migrations), then `just dev` (the worker starts and scans).
4. Watch progress on the Sources screen, or with `just vault-status`.
5. Network shares and WSL paths may not deliver file events. Rely on reconcile and consider lowering `SB_RECONCILE_MINUTES`.

## 10. Testing

### 10.1 Doubles and fixtures

- **Fake Ollama `/api/embed`** (extending the 1b fake):
  - returns a deterministic vector for each input (seeded from its sha256, 1024 values, unit length);
  - scriptable: down (connection refused), 404 "model not found", wrong size, wrong count, non-finite values, slow responses, failing on the Nth batch;
  - records every request.
- **Test vaults:** built under `tmp_path` per test by a small builder helper. A committed e2e fixture vault lives at `web/tests/e2e/fixtures/vault/` (5–8 short PL/EN notes).
- **Jobs:** run with the real procrastinate against the test database, using a helper that runs the worker until its queues are empty. Queues are cleared between tests.

### 10.2 Unit (no database; run on macOS and Linux CI)

1. **Normalization:** NFC vs NFD Polish text, a BOM, and CRLF vs LF each give the same hash; invalid UTF-8 → `encoding`.
2. **Parse:** the title fallbacks, frontmatter (valid, invalid, non-dict), wikilink forms, and links inside code ignored.
3. **Chunker:** heading paths, `#` inside fences, the 1600/200 rule at boundaries (1600 exact, 1601), paragraph → sentence → hard splits, empty sections, headingless notes, stable ordinals.
4. **Embedding text:** the text format with and without a heading path.
5. **Move pairing:** single pair, several candidates (the prefix rule), unpaired adds and deletes.
6. **Guard:** 10 of 40 → no trip; 11 of 40 → trip; 11 of 100 → no trip.
7. **Watcher:** real `watchfiles` on a temp dir with a recording stand-in for observe: create, modify, delete, rename, excluded folder, non-`.md` file. Generous timeouts; it asserts the eventual set of calls.
8. **Settings:** vault, embedding and URL rules, bounds, defaults, the fallback to the first chat endpoint.

### 10.3 Integration (Postgres; Linux CI)

1. **Observe idempotency:** the same file twice gives one revision and one job; a revert re-uses the old revision; touching the file without a content change triggers no re-index.
2. **Index swap:** an edit makes full-text search find the new words and not the old; the old revision is `superseded` with zero chunks; 10 quick saves → one `index_source` run indexes the newest, and the others are `superseded`.
3. **Crash mid-index:** an injected exception after the chunk inserts rolls everything back (the revision stays `pending`, the old chunks stay); a re-run succeeds.
4. **Crash between embedding batches:** a failure on batch 2 keeps batch 1's vectors; the re-run sends only the missing chunks, as the fake's request log shows.
5. **Ollama down:**
   - the note is `indexed` and found by full-text search, with `embed_error='embed_unreachable'`;
   - after the fake comes back, reconcile re-queues and embedding completes, clearing the error;
   - "model not found" → `embed_model_missing`, not retried; the Sources summary shows it.
6. **Delete / restore / move:**
   - a tombstone drops the note from full-text search, and the rows stay;
   - restoring the same content re-indexes;
   - a rename within one batch keeps the source id and creates no new revision;
   - a cross-batch move gives a new source plus a tombstoned old one.
7. **Offline changes:** with the worker stopped, create, edit and delete files; the startup reconcile brings the database to match.
8. **Guard:** missing vault → `vault_unavailable`, nothing tombstoned; removing >20% of more than 10 sources → `guard_tripped`, nothing tombstoned; `--allow-mass-delete` tombstones them.
9. **Recovery:** a `pending` revision without a job is re-queued; a current revision missing vectors is re-queued; a job stuck in `doing` for more than 10 minutes is reset (by moving the clock or setting the timestamp).
10. **API:** summary counts, listing with filters and cursor, retry (`202`, `409 nothing_to_retry`, `404`), manual reconcile (`202`, `409 vault_disabled`), login and same-origin checks.
11. **Schema:** the migrated test database matches what the installed procrastinate expects (its schema-check facility, or a comparison with its bundled SQL).
12. **Privacy:** `caplog` at DEBUG over tests 2–8 contains no note text, titles or paths; recorded job arguments contain only ids.
13. **Size:** an oversized file becomes `too_large` without being read (asserted by patching the read to fail).

### 10.4 Web

- **Vitest:** Sources summary cards, every banner, every badge state, retry and scan flows, filters and "Load more".
- **E2E (Playwright, Linux CI):** the harness also starts the worker with `SB_VAULT_PATH` set to the committed fixture vault and `SB_EMBED_URL` set to the fake Ollama. The test logs in, opens Sources, waits until every fixture note shows "Searchable", clicks **Scan now**, and sees "Last scan" update.

## 11. Docs and release

- **README:**
  - the vault and worker setup (§9);
  - the Sources screen, with a screenshot;
  - the mass-deletion guard;
  - the new `just` recipes;
  - troubleshooting for "model isn't installed" and "embedding host unreachable".
- **`.env.example`:** the seven new variables with comments.
- **ADRs:**
  - ADR-0003 → **Accepted** (procrastinate, vendored schema);
  - ADR-0006 → **Accepted** (bge-m3 as space 1; the bake-off moves to Phase 3).
- **`system-design.md` §9:** Phase 2 splits into 2a (this spec) and 2b (search, retrieval in chat, capture); Phase 3 narrows to the evaluation and bake-off.
- **Commits:** Conventional Commits to `main`, pushed once at the end of the phase (owner decision). CI releases **v0.4.0**.

## 12. Risks

| Risk | Mitigation |
|---|---|
| procrastinate misbehaves on Windows (selector loop, LISTEN/NOTIFY) | The first plan task is a smoke test on Windows. Fallback (ADR-0003 option C): a small `SKIP LOCKED` jobs table behind the same job functions. |
| bge-m3 on CPU is slow for a large first scan | Full-text search works immediately; embedding runs in the background with visible progress; batch size is tunable. |
| A wrong `SB_VAULT_PATH` wipes the index | Mass-deletion guard; `vault_unavailable` never tombstones; override only by CLI. |
| Missed watcher events (network drives, sleep) | Reconcile every `SB_RECONCILE_MINUTES`, plus at startup. |
| Private paths in logs | Logging rule §8, tested by §10.3 #12. |

## 13. Acceptance checklist

- [ ] Both migrations apply and roll back; `db/schema.sql` is regenerated.
- [ ] The §10.2 unit tests pass on Linux and macOS CI; the §10.3 integration tests pass on Linux CI.
- [ ] The §10.4 web tests pass, including the Sources e2e.
- [ ] `just check` is clean; the generated API client is current.
- [ ] README, `.env.example`, ADR-0003/0006 and system-design §9 are updated.
- [ ] Owner check: `just dev` against the real vault reaches all notes "Searchable" (owner-run, not CI).
- [ ] CI releases v0.4.0.

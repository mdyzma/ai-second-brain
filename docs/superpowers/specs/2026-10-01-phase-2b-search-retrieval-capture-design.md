# Phase 2b: search, retrieval in chat, and capture

Date: 2026-10-01 · Status: **approved design, spec under review** · Owner: Michal Dyzma
Parent docs: [system design](../../architecture/system-design.md) §2.3, §4.4, §4.5, §9 · ADRs [0006](../../architecture/adr/0006-embedding-spaces.md), [0012](../../architecture/adr/0012-salience-without-popularity-bias.md) · builds on [Phase 2a](2026-09-30-phase-2a-vault-ingestion-design.md) and [Phase 1b](2026-09-29-phase-1b-private-chat-design.md)

## 1. Purpose and success

Phase 2a made the vault a durable index. Phase 2b makes it useful:
- **Hybrid search.** Full-text plus bge-m3 vectors, fused with RRF, served by an API and a Search page.
- **Real retrieval in private chat.** Answers cite the notes they used.
- **A capture box.** A thought typed anywhere in the app becomes a Markdown note in the vault's `Inbox/`, and the 2a worker indexes it.

**Success (exit criteria):**
1. An exact identifier (e.g. `nas01`, an error code) and a paraphrase (Polish or English) each find the right note, through the API and the Search page.
2. Performance: hybrid search p95 < 400 ms over the fixture vault plus a synthetic 50k-chunk set. This is measured once with a script, not in CI.
3. A private-chat answer about a fixture note shows a source card for that note. Its `[n]` citations map to those sources. Cloud mode never retrieves.
4. A captured note is a real file in `<vault>/Inbox/`. While the worker runs, it is searchable within seconds.
5. Ollama down: search and chat fall back to full-text only and say so. Nothing fails.
6. No query text, capture text, note path or file name appears in logs. The privacy test proves this.
7. CI: Linux full suite plus e2e; macOS checks plus unit tests. CI releases v0.5.0.

## 2. Scope

**In:**
- the `search` module (one hybrid SQL query);
- `GET /api/search` and `GET /api/search/facets`;
- folder and tag filters, plus the tag column and migration;
- the real chat `Retriever`, with `num_ctx` for local chat;
- `POST /api/capture` and the capture dialog;
- the Search page;
- `obsidian://` links on search results and chat sources;
- tests, docs and screenshots.

**Out:**
- a note viewer inside the app;
- inline `#tags` in note bodies;
- date filters or sorting by date;
- filters in chat;
- salience priors and the "From earlier" slot (Phase 7, ADR-0012);
- cross-encoder re-ranking;
- searching chat history;
- capture from outside the app (MCP, mobile share target);
- editing or deleting notes from the app.

## 3. Settings

All `SB_*`, validated in `config.py`. A bad value is a startup configuration error.

| Variable | Default | Rule |
|---|---|---|
| `SB_CAPTURE_DIR` | `Inbox` | Relative to `SB_VAULT_PATH`. After normalisation it must stay inside the vault: no absolute path, no `..` that escapes. It must not be excluded by `SB_VAULT_EXCLUDE`, and it must not be an existing file. |
| `SB_OBSIDIAN_VAULT` | basename of `SB_VAULT_PATH` | The vault name used in `obsidian://open?vault=…`. Empty when no vault is configured. |
| `SB_CHAT_NUM_CTX` | `8192` | Integer from 2048 to 131072. Sent as `options.num_ctx` on local (Ollama) chat calls. |
| `SB_RETRIEVAL_MIN_SIMILARITY` | `0.45` | Float from 0 to 1. The cosine-similarity floor for vector-only hits in chat retrieval. Search does not use it. Phase 3 tunes it. |

Query embedding reuses `SB_EMBED_URL` / `SB_EMBED_MODEL` from 2a, so nothing leaves the LAN.

## 4. Database: one migration (`db/migrations/<ts>_search.sql`)

```sql
-- migrate:up
ALTER TABLE source_revisions ADD COLUMN tags text[] NOT NULL DEFAULT '{}';
CREATE INDEX source_revisions_tags_gin ON source_revisions USING gin (tags);
CREATE INDEX sources_external_ref_prefix ON sources (external_ref text_pattern_ops)
  WHERE deleted_at IS NULL;
-- backfill uses a temporary SQL mirror of normalise_tags (§5.1), dropped afterwards
CREATE FUNCTION pg_temp.sb_normalise_tags(value jsonb) RETURNS text[] ...;
UPDATE source_revisions r SET tags = pg_temp.sb_normalise_tags(r.metadata->'frontmatter'->'tags')
  WHERE r.state IN ('indexed', 'superseded');
-- migrate:down
DROP INDEX IF EXISTS sources_external_ref_prefix;
DROP INDEX IF EXISTS source_revisions_tags_gin;
ALTER TABLE source_revisions DROP COLUMN IF EXISTS tags;
```

The temporary function (list or comma/whitespace string; strip `#`, trim, lowercase, drop empties, de-duplicate in first-seen order, cap 64 × 100 characters) must apply the same normalisation as the Python `normalise_tags` (§5.2). The plan pins both to one shared test table of inputs and expected outputs: the SQL is tested against the same cases as the Python. `db/schema.sql` is regenerated, and `schema-check` stays green.

From 2b on, `knowledge/index.py` writes `tags` in `finish_index` (the same transaction as the chunks).

## 5. Search (`backend/src/ai_second_brain/search/`)

### 5.1 Module

- `query.py`, which exposes the function below.

  ```python
  query(conn, q, *, vector, folder=None, tags=(), limit=20, mode="search") -> SearchResult
  ```

  - **Arguments:** `vector` is a `list[float]` or `None`.
  - **Returns:** `SearchResult(hits: list[Hit], vector_used: bool)`.
  - **`Hit` fields:**
    - `source_id`, `path` (`external_ref`) and `title`;
    - `chunk_id` and `heading_path`;
    - `content`, the full chunk text;
    - `headline`, the `ts_headline` output or `None`;
    - `score`, the fused RRF score;
    - `matched`, a set of `"text"` and/or `"vector"`;
    - `similarity`, the cosine similarity, or `None` when there is no vector match.
- `tags.py`: `normalise_tags(value) -> list[str]`. It accepts a list, a comma- or whitespace-separated string, or anything else (giving `[]`). It strips a leading `#`, trims, lowercases, drops empties, and de-duplicates while keeping first-seen order. It keeps at most 64 tags of at most 100 characters each.
- `terms.py`: `chat_terms(question) -> ChatTerms` (§6.2).
- `links.py`: `obsidian_url(vault_name, path) -> str | None`. It percent-encodes `vault` and `file` (UTF-8, spaces become `%20`, `#` is encoded), passing the path with its `.md` extension. It returns `None` when `vault_name` is empty.

### 5.2 The hybrid query

There is one SQL statement with these CTEs. `$vec` is NULL when there is no vector, and the vector CTE then returns nothing.

1. **`live`.** Rows from `sources s` where `s.deleted_at IS NULL AND s.current_revision_id IS NOT NULL`, plus the optional filters:
   - folder: `s.external_ref LIKE $folder_prefix ESCAPE '\'`, where `$folder_prefix` is the escaped folder followed by `/%`;
   - tags: a join to the current revision with `r.tags @> $tags`.
   Only current revisions of live notes are searched, so pending, failed and superseded revisions and tombstones never appear.
2. **`fts`.** The top 50 chunks of live current revisions where `c.tsv @@ $tsq`, ranked by `ts_rank_cd(c.tsv, $tsq)` descending (ties broken by `c.id`). `row_number()` gives the rank.
   - **`mode="search"`:** `$tsq = websearch_to_tsquery('simple', q)`. Words combine with AND, and quotes and `-` work.
   - **`mode="chat"`:** `$tsq` is the OR query from §6.2, and the CTE also applies the chat match rule.
3. **`vec`.** The top 50 rows from `chunk_embeddings e` (with `e.space_id = $space`) ordered by `e.embedding::halfvec(1024) <=> $vec`. These are then joined to live current revisions.
   - Filtering after the HNSW scan can return fewer than 50 rows when the filters are narrow. That is acceptable. With filters, set `hnsw.ef_search = 200` for the statement (`SET LOCAL`).
   - `similarity = 1 - distance`.
4. **`fused`.** For each chunk, `score = Σ 1/(60 + rank)` over the lists it appears in. `matched` records which lists those were.
5. **Grouping.**
   - **`mode="search"`:** one row per source, its best-scoring chunk. Order by `score` descending, then by `path`, and take `limit`.
   - **`mode="chat"`:** up to 2 chunks per source, ordered by score. This feeds §6.

The headline is computed only for the returned rows:

```sql
ts_headline('simple', content, $tsq, 'StartSel=<mark>,StopSel=</mark>,MaxFragments=2,MaxWords=30,MinWords=12,FragmentDelimiter= … ')
```

Before calling `ts_headline`, the server escapes `&`, `<` and `>` in `content`. After it, it verifies that the only tags present are `<mark>` and `</mark>`. If anything else appears, it returns the escaped text without marks. For a vector-only hit, `headline` is `None`, and the API returns the first 240 characters of the chunk, escaped and cut at a word boundary.

### 5.3 Query embedding

The API embeds `q` with the existing 2a `Embedder` under a 1.5 s total timeout. That timeout covers one short input, not the batch timeouts. The API's `Embedder` is the one built in the 2a lifespan (`IngestAccess`). Its dims come from the default space, read at startup or lazily (not hard-coded).

Outcomes:
- No embedding host, the host is unreachable, the call times out, it returns a bad response, or the model is missing: in all these cases `vector = None`, and the result reports `vector_used = False`.
- The failure is logged with its code only (§10).
- A short circuit breaker applies. After a failure, further query embeddings are skipped for 30 s, so search doesn't pay 1.5 s per keystroke while Ollama is down.

### 5.4 API (session required; errors use the `{"detail": code}` format)

**`GET /api/search`** (operation id `searchNotes`)
- Parameters:
  - `q`: required. After trimming, 1–500 characters. NUL is rejected (422 `invalid_query`).
  - `folder`: optional, up to 500 characters. NUL is rejected. It is a vault-relative folder without a trailing `/`.
  - `tag`: repeatable, up to 10 values, each normalised with `normalise_tags`.
  - `limit`: 1–50, default 20.
- `200` returns:

  ```text
  {
    vector: "ok" | "unavailable",
    results: [{
      source_id, path, title, heading_path, snippet,
      matched: ["text", "vector"], score, obsidian_url
    }]
  }
  ```

  `snippet` is HTML-safe text containing only `<mark>` tags. `obsidian_url` may be `null`.
- `409 vault_disabled`: no vault is configured.
- `503 database_unavailable`: the database is unavailable.

**`GET /api/search/facets`** (operation id `searchFacets`)
- `200` returns:

  ```text
  {
    folders: [{ path, count }],
    tags: [{ tag, count }]
  }
  ```

  - `folders`: the first two path levels of live notes, sorted by path, with counts.
  - `tags`: tags from the current revisions of live notes, sorted by count descending and then by tag, at most 200 entries.
- The same 409 and 503 errors as `GET /api/search`.

Both routes live in `interfaces/api/routes/search.py`. The generated web client is regenerated.

## 6. Retrieval in private chat (`search/retriever.py`)

### 6.1 `HybridRetriever(pool, embedder_access, settings)` implements the 1b `Retriever` protocol

`retrieve(question, limit)` does the following:

1. Embeds the question (§5.3, with the same breaker).
2. Runs `query(..., mode="chat", limit=limit * 2)`. No filters are applied.
3. Applies the relevance cutoff:
   - a vector-only hit is kept only if `similarity ≥ SB_RETRIEVAL_MIN_SIMILARITY`;
   - a text hit is always kept, because it has already passed the chat match rule.
4. Applies the evidence budget. Chunks are taken in score order, at most 2 per note and at most `limit` (8) in total, until their content totals about 8,000 characters. A chunk that would exceed the budget is skipped, and the next one is tried.
5. Returns 1b `Source` objects:
   - `n` = 1…k in order;
   - `source_id`, `path`, `heading` (the heading trail joined with ` › `, or `None`);
   - `score`;
   - `snippet` = the full chunk `content`;
   - the new field `obsidian_url`.

`app.py` passes `HybridRetriever` instead of `NullRetriever` when a vault is configured. The CLI chat command does the same.

**Changes to the 1b models and events:**
- `Source` gains `obsidian_url: str | None = None`.
- The `receipt` event gains `retrieval: "hybrid" | "text_only" | "none"`:
  - `none`: cloud tier or no vault;
  - `hybrid`: the question was embedded, even if nothing matched;
  - `text_only`: the question could not be embedded.
- Both are optional or defaulted, so stored 1b turns still load.

### 6.2 Chat term rules (`chat_terms`)

The question is tokenised with the same `simple` parser: `ts_debug` in SQL, or a Python mirror tested against it.

- **Identifier-like terms:** a term that contains a digit, `.`, `-` or `_`, and is 2–64 characters long.
- **Other terms:** words of 3 or more characters, lowercased, kept as `simple` produces them. There is no stopword list. The 2-term minimum below does that job.
- **`$tsq`:** the OR of all terms, at most 16, keeping the identifier-like terms and the longest words.
- **The match rule** for a text hit in chat mode: the chunk matches at least one identifier-like term, or at least 2 distinct terms. It is computed in SQL from per-term `tsv @@ to_tsquery('simple', term)` checks on the ≤50 candidate rows.
- **A question with no usable terms** runs vector only.

### 6.3 Context window

`ollama.py` sends `"options": {"num_ctx": settings.chat_num_ctx}` on local chat calls. The existing 4xx-to-`context_too_long` mapping is unchanged.

### 6.4 Web

The existing chat source cards become plain `<a href>` links to `obsidian_url` when it is present, and the OS hands the link to Obsidian. Without a URL, they stay plain text. They show `path` and `heading`.

The receipt line shows "Searched your notes (text only)" for `text_only` and nothing extra for `hybrid`.

## 7. Capture

### 7.1 API: `POST /api/capture` (operation id `captureNote`; session + same-origin guard)

- Body: `{text}`. After trimming the ends, `text` is 1–20,000 characters. NUL is rejected (422 `invalid_text`).
- `201` returns `{path, title, obsidian_url}`.
- Errors:
  - `409 vault_disabled`: no vault is configured;
  - `409 capture_name_taken`: `(2)` through `(99)` are all taken;
  - `503 vault_unwritable`: an `OSError` while creating the directory or writing the file.

### 7.2 Writing the file (`vault/capture.py`, called through `asyncio.to_thread`)

**File name.**

```text
{YYYY-MM-DD HHmm} {title}.md
```

- The time is the server's local time.
- The title is built from the first non-empty line, in this order:
  1. strip leading `#` and whitespace;
  2. remove the characters `\ / : * ? " < > | # ^ [ ]` and control characters;
  3. collapse whitespace;
  4. cut to 60 characters at a word boundary when possible;
  5. strip trailing dots and spaces.
- If the result is empty, the title is `Capture`. Letters in any script are kept, so Polish works.

**Location.**
- The directory is `vault_root / SB_CAPTURE_DIR`, created with `mkdir(parents=True, exist_ok=True)`.
- The resolved path is checked again: it must be inside the resolved vault root and not a symlink. Otherwise the call fails with `vault_unwritable`.

**Creating the file.**
- `open(path, "x", encoding="utf-8", newline="\n")` creates it exclusively. On `FileExistsError`, it tries `name (2).md` and so on, up to `(99)`.
- It writes the content in one write, then flushes and `os.fsync`s. There is no temp file and no rename. A rename would wake a Windows rescan, as noted in the 2a follow-ups.

**Content.**

```markdown
---
captured: <ISO-8601 local time with offset>
source: app
---
<text exactly as submitted, with a trailing newline>
```

**Indexing.** The 2a worker indexes the file: the watcher within seconds, with reconcile as the backstop. The API does not index it itself.

### 7.3 Web: the capture dialog

**Opening it.** A "Capture" button in the app header opens the dialog, and so does the `c` key when focus is not in an input, a textarea or a contenteditable element.

**The dialog.**
- One textarea, autofocused. `Ctrl/Cmd+Enter` saves and `Esc` closes.
- **Draft:** the draft is kept in `localStorage` under one key (wrapped in try/catch) and cleared on success.
- **Success:** a toast says "Saved to Inbox", with an "Open in Obsidian" link when the response has a URL. The dialog closes.
- **Error:** the text stays, with mapped inline copy. The UI never shows server text:
  - `vault_disabled` → "No vault is configured. Set SB_VAULT_PATH."
  - `vault_unwritable` → "Couldn't write to the vault folder."
  - `capture_name_taken` → "Too many captures with this title this minute."
  - otherwise → the generic retry line.
- The Save button is disabled while saving and when the text is empty.

## 8. Web: the Search page (`/search`, replacing the placeholder)

`features/search/{types,api,labels,SearchScreen,SearchScreen.test}.ts(x)` and `routes/_app/search.tsx`.

**URL state.** `/search?q=&folder=&tag=&tag=` is the source of truth. Back and forward navigation work.

**Query box.** It is autofocused. A search runs after 250 ms of no typing once there are at least 2 characters; Enter runs it immediately. The query uses TanStack Query with `placeholderData: keepPreviousData`.

**Filters.**
- **Folder select:** "All folders" plus the facet folders.
- **Tag chips:** the 12 most-used tags. A "More…" popover lists the rest with a filter box. Selected tags combine with AND and carry `aria-pressed`.
- **"Clear filters"** appears when any filter is active.

**Result cards.** Each card shows:
- the title, linked to `obsidian_url` when it is present;
- the path in mono;
- the heading trail joined with ` › `;
- the snippet, rendered with only `<mark>` allowed (built from text nodes, never `innerHTML` of server text);
- "Text" and "Meaning" badges.

The result list supports arrow-key navigation, and Enter opens the selected note. A live region announces "N results".

**States.**
- **Empty query:** a hint, plus recent searches. These are the last 10 queries in this browser's `localStorage`, with a Clear button, and are never sent to the server.
- **Loading:** the previous results stay, dimmed.
- **No results:** "No notes match." When filters are active it adds "Try clearing the filters."
- **`vector: "unavailable"`:** an inline note, "Matching by meaning is unavailable right now; showing exact text matches."
- **`vault_disabled`:** "Set SB_VAULT_PATH to search your notes."
- **Other errors:** the mapped copy shared with Sources.

**Keys:** `/` focuses the search box, and `c` opens Capture.

**Styling:** tokens only, light and dark.

## 9. Privacy and logging

- **Search logs:** `search q_len=<n> filters=<count> results=<n> vector=<ok|unavailable> ms=<n>`.
- **Retrieval logs:** `retrieve q_len=<n> sources=<n> mode=<hybrid|text_only> ms=<n>`.
- **Capture logs:** `capture outcome=<ok|code> bytes=<n>`.
- **What is never logged:** query text, capture text, file names, note paths, snippets, or the exception messages of embed or OS errors. Only type names and codes are logged.
- Recent searches stay in the browser's `localStorage` only.
- **Cloud mode:**
  - it never calls the retriever, as in 1b;
  - capture and search never call cloud providers.
- **Privacy test:** the 2a privacy test (§10.3 #12 there) is extended to run search, chat retrieval and capture. It asserts that no fixture text, query, path or captured title appears in `caplog.text`.

## 10. Testing

### 10.1 Unit (no database)

- **`normalise_tags`:** list, string with commas and spaces, `#`, case, duplicates, non-string items, the 64/100 limits. These cases form the shared table that the SQL backfill test also uses.
- **`chat_terms`:** identifier detection (`nas01`, `192.168.1.10`, `ERR_TIMEOUT`, `v1.2`), the 3-character word minimum, the cap of 16 terms, and a question with no usable terms.
- **Capture title sanitising:** forbidden characters, the 60-character word-boundary cut, trailing dots, the `Capture` fallback, Polish letters, `# Heading` first lines.
- **`obsidian_url`:** spaces, `#`, `&`, Unicode, an empty vault name.
- **Evidence budget and per-note cap:** pure functions over `Hit` lists.
- **Settings:** `SB_CAPTURE_DIR` escaping the vault, absolute, or excluded; `SB_OBSIDIAN_VAULT` default; the numeric ranges.
- **Snippet safety:** headline post-check rejects any tag other than `<mark>`.

### 10.2 Integration (Postgres, fake Ollama; Linux CI)

1. **Exact identifier.** `nas01` is found by text only (`matched=["text"]`) when vectors are unrelated.
2. **Paraphrase.** The fake Ollama maps two texts to near vectors, and the note is found by vector only.
3. **Fusion.** A note matched both ways ranks first.
4. **Visibility.** Deleted, superseded, pending and failed revisions, and tombstoned sources, never appear.
5. **Filters.**
   - Folder prefix, including a folder named with `%` or `_`.
   - Tags AND.
   - Filters with a narrow match still return the matching notes.
6. **Vector unavailable.** With the fake down, the response has `vector: "unavailable"` and text results. The breaker skips the second call within 30 s.
7. **Facets.** Folder counts at two levels; tag counts; tombstoned sources are excluded.
8. **Migration backfill.** The SQL normalisation equals `normalise_tags` on the shared table.
9. **Chat retriever.** The match rule (one stop-like word doesn't match; an identifier does); the similarity cutoff; the per-note cap; the budget; `retrieval` in the receipt; cloud never retrieves; `num_ctx` sent to the fake Ollama.
10. **Capture.**
    - `201` creates exactly one file with the frontmatter and text. The next `201` with the same first line in the same minute gets ` (2)`.
    - `capture_name_taken` after `(99)` (faked).
    - `vault_disabled`.
    - `vault_unwritable` for a read-only directory (skipped where chmod can't apply).
    - No capture outside the vault through a symlinked capture dir.
    - The worker harness then indexes the file, and search finds it.
11. **Privacy.** The extended privacy test (§9).

### 10.3 Web (Vitest)

- **Search screen:** URL sync, the debounce (fake timers), each state, tag chips with `aria-pressed`, arrow and Enter keyboard navigation, the live region, snippet rendering with only `<mark>` (a `<script>` in a snippet renders as text), and the mapped errors.
- **Capture dialog:** the `c` shortcut ignored inside inputs, Ctrl+Enter, draft persistence, text kept on error, the toast with the Obsidian link.
- **Chat:** source cards link when a URL is present; the receipt shows text-only.

### 10.4 End to end (Playwright, fixture vault, real worker)

1. Search `Dyski`: `Projects/NAS.md` appears with `<mark>Dyski</mark>`.
2. Filter by tag `homelab`: only NAS remains.
3. Capture `Test capture e2e`: the toast appears. Searching `capture e2e` then shows the new `Inbox/…Test capture e2e.md`. The test waits on search results, not on a sleep.
4. Ask in private chat about the NAS backups: a source card for `NAS.md` appears.

The e2e reset script also deletes the fixture vault's `Inbox/` directory before the worker starts. `Inbox/` is git-ignored inside the fixture.

### 10.5 Performance check (script, not CI)

`backend/scripts/search_bench.py` seeds 50k synthetic chunks with random vectors into a scratch database, runs 200 mixed queries, and prints p50 and p95. The target is p95 < 400 ms on the owner's machine. The result is recorded in the README's architecture notes.

## 11. Docs and release

- **README:**
  - Search and Capture under "What it does today";
  - the settings table rows from §3;
  - the keys (`/`, `c`);
  - the Obsidian link and its limits: Obsidian must be installed on the device that opens the link;
  - troubleshooting: "Matching by meaning is unavailable" and "Couldn't write to the vault folder";
  - two screenshots: `search.jpg` and `ask-sources.jpg`.
- **`system-design.md` §9:** 2b is **delivered**.
- **ADR-0012:** a note that salience priors remain for Phase 7. 2b ranks by RRF only.
- **CI** releases v0.5.0 from the `feat` commits.

## 12. Risks

| Risk | Mitigation |
|---|---|
| HNSW with post-filtering returns too few rows under narrow filters | `SET LOCAL hnsw.ef_search = 200` with filters; text hits still appear; tested in §10.2 #5 |
| Ollama latency makes search-as-you-type slow | 1.5 s cap, a 30 s breaker after a failure, a 250 ms debounce, previous results kept on screen |
| `simple` config has no Polish stemming, so inflected words miss in full-text | The vector side covers meaning; full-text is for exact identifiers. Revisit in Phase 3. |
| The chat OR query is too loose | The match rule (identifier or ≥2 terms), RRF, and the similarity floor for vector-only hits |
| Capture writes into the owner's vault | Exclusive create only; a containment and symlink check; never overwrite; a fixed frontmatter; text as typed |
| `ts_headline` output used as HTML | Server escapes first and verifies only `<mark>`; the client builds DOM from text nodes |

## 13. Acceptance checklist

- [ ] Migration, schema-check and backfill test pass.
- [ ] Unit, integration, web and e2e tests in §10 pass, including the extended privacy test.
- [ ] `just check` is clean; the API client is current.
- [ ] Docs and screenshots are updated.
- [ ] The performance script meets p95 < 400 ms on the owner's machine.
- [ ] Owner check: with `just dev` against the real vault, search finds a known note by identifier and by meaning; a private chat answer cites it; a capture appears in Obsidian and in search.
- [ ] CI is green on Linux and macOS and releases v0.5.0.

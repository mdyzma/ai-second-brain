# Phase 2a: follow-up backlog

Date: 2026-10-01. Source: the task reviews and the final whole-branch review of Phase 2a (durable vault ingestion). Every item below was **triaged as "later"**: none blocks Phase 2a.

These items were fixed before release and are not listed:
- the review's nine Important findings:
  - Windows rescans on every save;
  - tombstones during a walk;
  - chunks coming back on a deleted note;
  - index jobs waiting behind the embed backlog;
  - Retry emptying an unreadable note;
  - the "Scan now" notice;
  - the worker stopping on a DB restart;
  - case-only renames on Windows;
  - the privacy test;
- symlinked notes in watcher events;
- the Embedded card title;
- failed-only sources that were never tombstoned;
- a scan that was already queued;
- a unique-violation path leak;
- rescanning after the watcher recovers;
- docs drift.

## Watch in CI

- **e2e worker path:** the worker web-server entry has only run on Windows. Its first Linux run is the push.
- **Case-only rename batch test:** it proves the bug only on case-insensitive disks (Windows and macOS). On Linux it passes either way.

## Behaviour worth improving

- **Temp-file saves still wake a rescan.** A deleted non-`.md` path, such as `x.md.tmp`, requests a rescan (coalesced to one per 10 s). A safe refinement: on a non-`.md` `deleted` event, rescan only if a live source sits under `rel + "/"`. Filtering by suffix would miss a deleted folder named `v1.2`.
- **State after an undo:** undoing before indexing can report a source as `superseded`, so it drops out of the Indexed count and the Searchable filter. Bump the current revision's `observed_at`, or derive the state from the current revision (final review M3).
- **No embedding host at all:** Sources shows no warning when there is no embedding host at all (spec §3; final review M6).
- **Concurrent observes of one path:** these can index the older read until the next reconcile. Order by `mtime_ns` (M7).
- **Large-vault cost:**
  - New files are read twice per pass.
  - Every pass re-defers every not-fully-embedded revision (M9).
- **Scan notices:**
  - The scan notice is not cleared when a scan completes.
  - `_supervise` logs `database_unavailable` for any worker exit.
- **Advisory lock hold time:** the reconcile's disk re-check runs while it holds the advisory lock, which is slow on a network vault.
- **API job app:**
  - Cancellation mid lazy-open can leave a pool that was never confirmed.
  - While the DB is down, requests serialise behind the 2 s open. A negative cache would help.
- **Reconcile counts:**
  - An unreadable new file is dropped without an `io_error` count.
  - A file that failed on encoding is re-observed as changed on every pass.
  - The requeue counts include `AlreadyEnqueued`.
- **Summary queries:**
  - `last_error` counts `embed_error` on every current revision.
  - `list_sources` runs its subqueries before the LIMIT.
  - The CLI skips the worker's embed-model check.
- **Parsing edge cases:**
  - empty frontmatter and the `...` closer;
  - setext headings;
  - a bare `#`, and `# ##`;
  - 4-space-indented fences, and closing fences with an info string;
  - multi-backtick inline code;
  - `![[embeds]]` counted as links;
  - `fnmatchcase` is case-sensitive on Windows and macOS;
  - file names are not NFC-normalised.
- **Chunking:** `_overlap` can drop a whole leading word, and 1399–1600-char paragraphs are sentence-split needlessly.
- **Embedder:**
  - `embed()` catches only timeout and transport errors.
  - A 429 maps to `bad_response`.
  - `embed([])` is unguarded.
- **Index failure handling:** `mark_index_failed` marks every pending revision failed, not just the one it claimed.
- **Settings messages:** `SB_VAULT_PATH="   "` reports "not absolute". `model_matches_space` is case-sensitive.
- **Worker on Windows:**
  - Ctrl+C takes up to ~5 s with the selector loop.
  - `CancelledError` is suppressed while the worker awaits its children at shutdown.

## Test gaps

- **Cross-process locking:** there is no test that the advisory lock serialises two processes' move/tombstone phases.
- **Untested logs and paths:**
  - `batch_guard_tripped` log;
  - `worker_exited`;
  - the reconcile stalled-skip path;
  - the lifespan skipping close when the job app never opened.
- **Sources route:** no route-level web test for the poll wiring or for full-screen vs inline errors.
- **Parser and chunker:** CRLF frontmatter, `~~~` fences, sentence splitting, an upper bound on overlap.
- **Embedder test:** the 307 test has no Location header, so it doesn't prove redirects aren't followed.

## Housekeeping

- Add a `.gitattributes` `eol=lf` for `db/**/*.sql`.
- `vendored_up_sql` strips any "-- Vendored"/"-- Upgrading" line, not just the header.
- `jobs.py` repeats the embed retry tuple instead of importing it.

# Phase 2b: follow-up backlog

Date: 2026-10-01. Source: the task reviews and the final whole-branch review of Phase 2b (search, retrieval in chat, capture). Every item below was **triaged as "later"**: none blocks Phase 2b.

These were fixed before release and are not listed:
- **Model loading:** the cold-model timeout and breaker.
- **Test safety:** the e2e reset deleting outside the fixture vault.
- **Search page:**
  - Back/Forward between searches;
  - remembering only committed searches, not debounced prefixes;
  - search-link scheme guard;
  - the heading trail repeating the title;
  - the stale result count in the live region.
- **Capture:**
  - text typed during a save;
  - double submit;
  - session-expired copy;
  - empty files left by a failed capture write;
  - a capture directory that is a file.
- **Performance:**
  - generic-plan slowness (`prepare=False`);
  - chat match-rule cost.
- **Privacy test:** its scope.
- **Excerpts:** splitting an entity.

## Watch in CI

- **e2e:** one unidentified e2e failure was seen locally before a strict-mode locator fix. Later runs were green.
- **Case-only renames:** carried from 2a. The test proves only case-insensitive disks.

## Behaviour worth improving

- **Search URL shape:**
  - The tag filter serialises as a JSON array (`tag=%5B%22homelab%22%5D`) instead of spec §8's `tag=a&tag=b`.
  - A hand-typed `?q=404` parses as a number and is dropped.
  - Fix: a router-wide `parseSearch`/`stringifySearch` with repeated keys.
- **Search history:** Search history can get a duplicate entry. It happens when Enter is pressed on an unchanged query, or when the text is typed back to the committed query (history state `{}` vs `{searchDraft:false}`).
- **Shared breaker:** search and chat share one query-embedding breaker. A cold-model search timeout (1.5 s) can make a chat question in the next 5 s text-only, despite chat's 8 s allowance.
- **Missed chat matches:** chat retrieval drops chunks that pass the match rule but rank below 200 in the OR query (by design; the vector arm can still find them).
- **Narrow filters:** they can miss vector hits, because filtering happens after a 200-candidate HNSW scan. pgvector 0.8 `hnsw.iterative_scan` would fix it.
- **Folder index under generic plans:** the folder `LIKE` prefix index isn't used under generic plans. Search runs with `prepare=False`, so this only matters if that changes.
- **Live CTE guard:** the `live` CTE doesn't also check `r.state = 'indexed'`. That's safe today, because chunks are deleted on supersede.
- **Snippet highlights:** a headline mark can split an HTML entity (`&<mark>amp</mark>;`). Cosmetic and safe.
- **Chat headlines:** a headline is computed for chat rows that never use it.
- **Saved turns:** the retrieval mode isn't saved per turn, so reloaded history never shows "Searched your notes (text only)".
- **`SB_CAPTURE_DIR="."`:** accepted, so captures would go to the vault root.
- **Capture limits:**
  - The 20,000-character limit is checked before trimming.
  - C1 controls and bidi overrides survive in capture titles.
- **Embedder errors:** `QueryEmbedder` logs a bad response as `embed_timeout`. There's no single-flight while the embedder is down: concurrent requests each wait up to the cap.
- **Prompt escaping:** `&` is not escaped in chat evidence (harmless).
- **Keyboard shortcut:** the `c` shortcut checks only the capture dialog, not other open dialogs.

## Test gaps

- **Search query:**
  - search-mode cap of 1 on a multi-chunk note;
  - fusion order against a text-only rank-1 chunk;
  - a backslash folder;
  - reindex then search an old word;
  - chat with empty terms;
  - the `_safe_headline` fallback.
- **Migration:** the backfill `UPDATE`s on pre-existing rows; Unicode whitespace (NBSP) parity for tags.
- **Facets:** tombstoned notes, 401, `vault_disabled`.
- **Search page:**
  - the pending-debounce guard;
  - the "Searching…" state;
  - malformed `<mark>`;
  - recent-search clear at hook level.
- **Capture dialog:**
  - the status timer reset and unmount;
  - focus in and out;
  - chat-composer exclusion from the `c` shortcut;
  - a real read-only-directory capture.
- **Settings:** `C:foo`, UNC and trailing-slash `SB_CAPTURE_DIR` cases.

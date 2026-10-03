# Phase 3: follow-up backlog

Date: 2026-10-03. Source: the task reviews and the final whole-branch review of Phase 3 (embedding evaluation). Every item below was **triaged as "later"**; none blocks Phase 3.

## Fixed before release

- an ETA on progress;
- clear runtime errors, with resume and prepare hints;
- per-model query prefixes;
- `--models` relabel and validation;
- duplicate model tags;
- a cache keyed by model digest;
- Ctrl+C keeping the cache and exiting 130;
- a private fallback report folder;
- recipe paths resolved from the repo root;
- UTF-8 CLI output on Windows;
- `eval suggest --out`;
- the repeatable-read snapshot;
- keeping the seed space in the scratch DB.

## Behaviour worth improving

- **Large vaults:** chunk inputs are held in memory per model. That's fine at ~50k chunks, but not at 500k or more. Stream rows with a server-side cursor (M4).
- **Missing scratch DB without access to `postgres`:** when the user can't open `postgres`, a missing scratch database is reported as "unreachable" instead of showing the `just eval-prepare` hint.
- **Guard gaps:** the URL guard doesn't percent-decode database names, doesn't handle `?host=` overrides and doesn't treat `0.0.0.0` as local. A `DATABASE_URL` without a path gives the eval database `"/_eval"`. Host aliases slip past the identity check; `check_ready` still blocks writes.
- **Ids:** `str(id)` makes `5` and `"5"` collide in the query loader.
- **Strict typing:** `query()` doesn't use `isinstance(int)` on `space_id` and `dims`, so a bool gives a database error rather than a ValueError.
- **Snowflake as production model:** if `SB_EMBED_MODEL` is ever set to snowflake, production search must add the `query: ` prefix (Phase 3b).

## Test gaps

- an end-to-end check of the bootstrap argument order;
- chat mode with `text=False`;
- `query()`-level HNSW use (the existing test uses raw SQL);
- IDLE assertions on the new embedding error paths;
- a second-run seed rename;
- `model_digests` success and the per-model topic paths;
- untested edge cases:
  - empty bootstrap and empty percentile;
  - a `split_by` length mismatch;
  - the `[::1]` host;
  - a symlinked `eval_dir`;
  - an autocommit or swapped dev connection.

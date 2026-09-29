# Phase 1a: follow-up backlog

Date: 2026-09-29. Source: the task reviews and the final whole-branch review of Phase 1a (v0.2.0, fixed in v0.2.1). Every item below was **triaged as "later"**: none blocks Phase 1a. Items that were fixed in the final fix wave are not listed. They are request logging, test isolation from `.env`, cookie clearing on a failed logout, hiding secret input in errors, revert commits not releasing, stale-session revalidation and README accuracy.

## Before exposing the API beyond localhost

- Cap the request body size. The 1024-character password limit applies only after the whole JSON body has been read.
- The login throttle is global, not per client, so anyone who can reach the API can lock the owner out. Rethink it together with network exposure (the spec defines the current global behaviour).
- Pin third-party GitHub Actions to commit SHAs in the `release` job, which has `contents: write`.
- Protect `v*` tags with a GitHub ruleset (Settings → Rules → Rulesets → Tag rules).

## With Phase 1b (first real data)

- **API version:** `openapi.json` `info.version` is hard-coded to 0.2.0. Decide between a separate contract version and deriving it from the app version. If it is derived, `set-version` must also regenerate the client, or `api-client-check` fails after every release.
- **Login UX:**
  - `/me` failing after a successful login, or a network error, sends the user back to `/login` with no visible message, and `handleSubmit` has an unhandled rejection.
  - A 403 is shown as "Can't reach the server".
- **Sessions:**
  - Logging in again doesn't revoke the previous session.
  - `/me` doesn't clear an invalid cookie.
  - The login lock is held during `store.create`, so with the database down, queued logins each wait for a pool timeout.
- **Database errors:** `PoolClosed` and `InterfaceError` are not mapped to 503. A cancelled request (client disconnect) is logged as 500.
- **Guard:** with `revalidateIfStale`, a revoked session passes the guard once when stale. The cache corrects itself afterwards.

## Tooling and tests (housekeeping)

- **`scripts/`:**
  - `schema-check` prints the same `SKIPPED` for "no Docker" and "container down".
  - `normalize()` is exported from a script with top-level side effects.
  - `db-up` hard-codes the `127.0.0.1:5433` message and prints a relative `-f` path.
- **`set-version`:**
  - The writes are not atomic.
  - The TOML line parser misses `[[array-tables]]` and `[project] # comment`, drops trailing comments, and mixes line endings on CRLF files.
  - No test checks that it exits non-zero without touching any file.
  - `assertSemver` accepts leading zeros.
- **Release notes:**
  - The heading is the preset's "⚠ BREAKING CHANGES".
  - Git-generated `Revert "…"` commits (with no type) may still release a PATCH. To cover them, add `{"revert": true, "release": false}` to `.releaserc.json`.
  - The `^9` pin of `conventional-changelog-conventionalcommits` needs a note: v10 requires conventional-changelog-writer 9, while semantic-release 25 bundles 8.
- **commit-msg hook:** `claude.ai/code` also matches `claude.ai/codex`. The prose "written by Claude" is rejected; this is intentional.
- **Web checks:**
  - `check-colors` flags valid-hex anchors such as `#dead` and `#face`.
  - It misses named colours, `color()` and `color-mix()`.
  - It skips any `api` directory, at any depth.
  - The checker tests don't cover the dark override, a 3:1 failure or comment stripping.
- **Web app:**
  - The theme has no cross-tab sync.
  - Logout has no double-click guard.
  - At 375 px the bottom bar scrolls horizontally.
  - There are two "Primary" nav landmarks, with one hidden per breakpoint.
  - `tsr generate` prints a circular-dependency warning, which comes from the tooling.
- **Backend:**
  - `pool.close(timeout=0.1)` may let in-flight connection attempts finish after close.
  - The `ready` route lacks a return annotation.
  - `app.state.pool` exists only inside the lifespan.
  - `purge_expired` adds about 2 s per test app started against a dead database.
  - The throttle tests don't cover exact boundaries or increments while locked.
- **CLI:**
  - The mismatch test doesn't assert that the retry succeeds.
  - The `serve` argument forwarding is untested.
  - `--port 0` is treated as unset.
  - `openapi` to stdout is not LF/UTF-8 safe on Windows (the recipes use `--output`).
  - `SRC_DIR` is misnamed.
- **CI and e2e:**
  - The e2e output includes uvicorn INFO lines.
  - The e2e step timeout could be 5 minutes.
  - The install recipes could use `--frozen`/`--locked`.
  - The Playwright config has a duplicated comment.
  - `setup-uv@v6` and `setup-just` print Node 20 deprecation warnings.
  - `just install` always downloads Chromium.
- **Misc:**
  - `init-env` only warns about missing keys.
  - `@types/node ^26` doesn't match `engines >=24`.
  - Alias tokens are defined only on `:root`, which is fine while `data-theme` sits on `<html>`.

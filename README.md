# Second Brain

Private-by-default personal knowledge system: notes, documents, engineering history and home-lab
hardware in one searchable memory, with private data processed only on your own machines.

- Architecture and decisions: [docs/architecture/](docs/architecture/README.md)
- Current phase spec: [Phase 1a foundation](docs/superpowers/specs/2026-09-29-phase-1a-foundation-design.md)

## Prerequisites

|  | Windows | macOS (Apple Silicon) | Linux |
|---|---|---|---|
| uv, just | `winget install astral-sh.uv Casey.Just` | `brew install uv just` | official install scripts or distro packages |
| Node 24 | `winget install OpenJS.NodeJS.LTS` (or fnm) | `brew install fnm && fnm install` (reads `.nvmrc`) | fnm / nvm |
| pnpm | `corepack enable` | `corepack enable` | `corepack enable` |
| Docker | Docker Desktop | Docker Desktop or OrbStack | Docker Engine |

Python 3.12 is installed automatically by uv. dbmate comes with the pnpm workspace.

## Quick start

Run every `just` command from the repository root.

```bash
just setup          # deps, .env, Postgres container, migrations (Docker must be running)
just hash-password  # prints SB_OWNER_PASSWORD_HASH='...'; paste it into .env, keeping the quotes
just dev            # API + web; open http://localhost:5173
```

## Everyday commands

| Command | What it does |
|---|---|
| `just check` | Lint, format check, type checks, token contrast, API-client and schema freshness |
| `just test` | Backend (unit + integration) and web unit tests |
| `just test-unit` | Tests that need no database |
| `just e2e` | Playwright login/navigation tests against the test database |
| `just fmt` | Format and auto-fix |
| `just db::new <name>` then `just db::migrate` then `just db::dump` | Add a migration and refresh `db/schema.sql` |
| `just api-client` | Regenerate the TypeScript client after changing API models |
| `just --list` | Everything else |

## Layout

`backend/` Python API and CLI (uv) · `web/` React + TypeScript UI (pnpm) · `db/` SQL migrations
(dbmate) · `infra/` Docker Compose · `scripts/` cross-platform helper scripts · `docs/` design docs.

## Notes

- `.env` is never committed. `.env.test` is committed on purpose and contains only test values
  (the e2e password is `e2e-test-password`).
- Keep the single quotes around `SB_OWNER_PASSWORD_HASH`. Without them, just's `.env` loader
  expands the `$` characters and the hash breaks.
- If the npm dbmate binary can't be downloaded (proxy/offline), install dbmate with scoop/winget
  or `brew install dbmate`, and set `DBMATE=dbmate` in `.env`.
- The dev database listens on `127.0.0.1:5433`. Use the IP, not `localhost`, which is slow on
  Windows.

## Commit messages

Conventional Commits: `type(scope): summary`. The header is imperative, ≤ 50 characters
(72 is the hard limit) and has no period. An optional body explains what and why, wrapped at
72. The optional footer holds `BREAKING CHANGE:` / `Closes #n`. AI attribution
(`Co-Authored-By`, "Generated with Claude") is never allowed. The `commit-msg` hook in
`.githooks/` enforces this. `just install` enables it (`just hooks` on its own).

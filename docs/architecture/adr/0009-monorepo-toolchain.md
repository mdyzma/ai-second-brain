# ADR-0009: Monorepo toolchain — uv + pnpm, orchestrated by just

**Status:** Accepted (owner decision) — this ADR records the details
**Date:** 2026-09-29
**Deciders:** Michal Dyzma

## Context

The stack spans Python (backend), TypeScript (web), SQL (migrations) and infra (compose, Caddy, systemd). The owner chose **uv** for Python and **just** as the cross-stack command runner. Poetry from the MVP is dropped.

## Decision

- **One repository**: `backend/`, `web/`, `db/`, `infra/`, `docs/`, plus a root `justfile`.
- **Python:** uv project in `backend/` (`pyproject.toml`, `uv.lock`, `.python-version` = 3.12). Dev tools as uv dependency groups: ruff (lint + format), pyright (types), pytest, import-linter. Everything runs as `uv run …`.
- **Node:** pnpm in `web/`, versions pinned (`packageManager` field, `.nvmrc`).
- **Database:** dbmate for migrations (see ADR-0004), invoked via just.
- **just is the only documented interface.** Nobody needs to remember `uv`/`pnpm`/`dbmate` flags. Just modules (`mod backend`, `mod web`, `mod db`) keep the root file short.

### Root `justfile` shape

```just
set dotenv-load
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]   # owner develops on Windows (PowerShell 5.1; no sh)

mod backend 'backend/justfile'
mod web 'web/justfile'
mod db 'db/justfile'

default:
    @just --list --list-submodules

setup:                       # fresh clone → working env
    uv --directory backend sync
    pnpm --dir web install
    docker compose -f infra/compose.yaml up -d postgres
    just db::migrate

dev:                         # api + worker + vite, prefixed logs
    ...                      # e.g. via `concurrently` or `process-compose`

check: backend::check web::check api-client-check
test:  backend::test web::test
build: api-client web::build
api-client:                  # OpenAPI → web/src/api
    uv --directory backend run ai-second-brain openapi > web/src/api/openapi.json
    pnpm --dir web exec openapi-typescript src/api/openapi.json -o src/api/schema.d.ts
api-client-check: api-client
    git diff --exit-code web/src/api
```

## Options Considered

| Option | Verdict |
|---|---|
| **uv + pnpm + just (chosen)** | Fast, lockfiles on both sides, one entry point |
| Poetry + npm + Make | Make is awkward on Windows and with arguments; Poetry is slower and cannot manage Python versions |
| Nx / Turborepo | Built for JS monorepos; adds a second orchestrator on top of just |
| Pants / Bazel | Far too heavy for one developer |

## Consequences

- CI runs exactly `just setup && just check && just test`, the same as local.
- Windows + Linux: recipes must work in both pwsh (dev) and bash (Proxmox/CI). Use `[unix]`/`[windows]` attributes where commands differ.
- Revisit: `just dev` process management. Start simple (`concurrently` from web devDependencies). Switch to `process-compose` if restart/health handling is needed.

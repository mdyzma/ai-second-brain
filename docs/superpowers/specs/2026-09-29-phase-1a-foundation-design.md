# Phase 1a: foundation scaffold

Date: 2026-09-29 · Status: **approved design, spec under review** · Owner: Michal Dyzma
Parent docs: [system design](../../architecture/system-design.md) §2.2, §7, §9 · ADRs [0001](../../architecture/adr/0001-modular-monolith.md), [0004](../../architecture/adr/0004-data-access-and-migrations.md), [0009](../../architecture/adr/0009-monorepo-toolchain.md), [0010](../../architecture/adr/0010-web-ui-stack.md) · [design system](../../architecture/design-system-audit.md)

## 1. Purpose and success

Replace the discarded MVP with the greenfield monorepo on which every later phase builds. 1a delivers **no knowledge features**. It proves the toolchain, the backend ↔ database ↔ web path, authentication and the design-system foundation.

**Success (exit criteria):**
1. On a fresh clone with the prerequisites (§9) installed and the Docker daemon running, `just setup` followed by `just dev` lets the owner open the web UI, log in with the configured password, and see the protected app shell in light and dark themes.
2. `just check`, `just test` and `just e2e` pass locally on Windows (PowerShell) and in GitHub Actions on Ubuntu. On macOS (Apple Silicon, the owner's M1), `just setup`, `just dev`, `just check` and `just test` work locally, and CI runs `just check` + `just test-unit` on `macos-latest`.
3. The old MVP files are gone from the tree.

**Decisions taken with the owner:** include real login; add GitHub Actions CI; delete the old code (git history keeps it); `just dev` uses a local Docker Postgres by default.

## 2. Scope

**In:** repository layout, root justfile, backend skeleton (config, DB pool, auth, health, admin CLI), first migration, web skeleton (routing, auth guard, shell, tokens, primitives), generated API client, tests, CI, README rewrite, `.env.example`.

**Out:** chat, retrieval, embeddings, Ollama, the job worker (procrastinate), the Obsidian sync, Caddy/TLS and production deployment, import-linter contracts (added with the first domain modules in 1b/2), MCP, Storybook.

## 3. Repository layout after 1a

```
ai-second-brain/
├── justfile                    # root recipes; imports modules below
├── package.json                # private pnpm workspace root: dbmate, concurrently, tsx
├── pnpm-workspace.yaml         # packages: [web]
├── .env.example                # all variables, commented
├── .nvmrc                      # 24
├── .gitattributes              # * text=auto eol=lf
├── scripts/                    # cross-platform TS helpers run with tsx (no shell-specific logic in recipes)
│   ├── wait-for-db.ts
│   └── schema-check.ts
├── backend/
│   ├── justfile
│   ├── pyproject.toml          # uv project "ai-second-brain", requires-python >=3.12
│   ├── uv.lock
│   ├── .python-version         # 3.12
│   ├── src/ai_second_brain/
│   │   ├── __init__.py
│   │   ├── config.py           # Settings (pydantic-settings)
│   │   ├── db.py               # async pool lifecycle + readiness check
│   │   ├── auth/
│   │   │   ├── __init__.py
│   │   │   ├── passwords.py    # argon2 hash/verify
│   │   │   ├── sessions.py     # SessionStore (create/get/touch/revoke/purge)
│   │   │   └── throttle.py     # login failure lockout
│   │   └── interfaces/
│   │       ├── api/
│   │       │   ├── __init__.py
│   │       │   ├── app.py      # create_app() factory, lifespan, routers
│   │       │   ├── deps.py     # get_pool, current_session, require_same_origin
│   │       │   ├── schemas.py  # Pydantic request/response models
│   │       │   └── routes/{health.py, auth.py}
│   │       └── cli/
│   │           └── main.py     # Typer app: serve, openapi, hash-password
│   └── tests/{unit/, integration/, conftest.py}
├── web/
│   ├── justfile
│   ├── package.json, tsconfig*.json, vite.config.ts, biome.json, playwright.config.ts
│   ├── index.html
│   ├── src/
│   │   ├── main.tsx
│   │   ├── api/                # openapi.json + schema.d.ts (generated) + client.ts (hand-written wrapper)
│   │   ├── design-system/
│   │   │   ├── tokens.css      # palette → semantic → domain tokens, light + dark
│   │   │   ├── ui/             # shadcn primitives: button, input, label, card, sonner
│   │   │   ├── theme.tsx       # ThemeProvider + toggle (system / light / dark)
│   │   │   └── AppShell.tsx    # sidebar + header layout
│   │   ├── features/auth/      # LoginForm, useSession, auth queries
│   │   └── routes/             # __root, login, _app (guard), _app/{ask,search,projects,digest,review,nodes,sources,settings}
│   ├── scripts/{check-contrast.ts, check-colors.ts}
│   └── tests/{unit/, e2e/}
├── db/
│   ├── justfile
│   ├── migrations/20260929000000_init.sql
│   └── schema.sql              # dbmate dump, committed
├── infra/compose.yaml
├── .github/workflows/ci.yml
└── docs/
```

**Deleted:** `src/`, `tools/`, `tests/` (old), `pyproject.toml`, `poetry.lock`, `sql_migrations/`, `docker-compose.yml`, the old `justfile` (rewritten), and the README content about the old setup (rewritten).

## 4. Configuration

A single root `.env` (git-ignored). just loads it with `set dotenv-load`, and the backend reads it through pydantic-settings.

| Variable | Used by | Dev default in `.env.example` | Notes |
|---|---|---|---|
| `DATABASE_URL` | dbmate, backend | `postgres://brain:brain@localhost:5432/ai_second_brain?sslmode=disable` | Shared by both |
| `TEST_DATABASE_URL` | dbmate, pytest | `…/ai_second_brain_test?sslmode=disable` | Created by `just db::test-prepare` |
| `SB_OWNER_PASSWORD_HASH` | backend | empty. `just setup` prints a hint to run `just hash-password` | argon2id encoded string |
| `SB_SESSION_TTL_DAYS` | backend | `14` | Sliding expiry |
| `SB_COOKIE_SECURE` | backend | `false` | `true` in production |
| `SB_ALLOWED_ORIGINS` | backend | `http://localhost:5173` | Comma-separated; used by the CSRF check |
| `SB_API_PORT` | just, vite proxy | `8000` | |
| `SB_ENV` | backend | `dev` | `dev` enables `/api/docs`; `prod` disables it. Allowed values: `dev`, `prod` |

`Settings` rejects startup when `SB_OWNER_PASSWORD_HASH` is empty or not an argon2 string. The error message names the fix (`just hash-password`). For `just dev`, a missing hash stops the API with that message.

## 5. Database

The dbmate migration `20260929000000_init.sql`:

```sql
-- migrate:up
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE auth_sessions (
    id            bytea PRIMARY KEY,              -- sha256(token); the raw token exists only in the cookie
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_seen_at  timestamptz NOT NULL DEFAULT now(),
    expires_at    timestamptz NOT NULL,
    user_agent    text
);
CREATE INDEX auth_sessions_expires_idx ON auth_sessions (expires_at);

-- migrate:down
DROP TABLE auth_sessions;
DROP EXTENSION IF EXISTS vector;
```

The `vector` extension is enabled now so that environment problems (a wrong image, a missing extension) surface in 1a, not in phase 2. `schema.sql` is committed, and `just check` verifies it is current (`dbmate dump` then `git diff --exit-code db/schema.sql`) when a database is reachable.

## 6. Backend

**Dependencies:** fastapi, uvicorn[standard], pydantic-settings, psycopg[binary,pool] ≥ 3.2, argon2-cffi, typer.
**Dev dependencies (uv group `dev`):** pytest, pytest-asyncio, httpx, ruff, pyright.

### 6.1 Components

- `config.Settings`: the table in §4, cached through `get_settings()`, overridable in tests.
- `db`: creates `psycopg_pool.AsyncConnectionPool` in the FastAPI lifespan (min 1, max 5, `open=False`, opened on startup, closed on shutdown). `ping(pool)` runs `SELECT 1` with a 2 s timeout.
- `auth.passwords`: `hash_password(plain) -> str` and `verify_password(hash, plain) -> bool` using argon2-cffi defaults (argon2id). Verification failures return `False`, never raise.
- `auth.sessions.SessionStore(pool)`:
  - `create(user_agent) -> str` generates `secrets.token_urlsafe(32)`, stores its sha256, and returns the raw token.
  - `get(token) -> Session | None` returns only unexpired sessions.
  - `touch(session)` extends `expires_at = now() + ttl` and `last_seen_at`, at most once per 5 minutes, to limit writes.
  - `revoke(token)` deletes the session.
  - `purge_expired()` runs on API startup.
- `auth.throttle.LoginThrottle`: in-process. After 5 consecutive failures, login is rejected for 60 s (HTTP 429 with `Retry-After`). It resets on success. Process-local state is acceptable for a single-user, single-process API. Documented as such.

### 6.2 API

| Route | Auth | Behavior |
|---|---|---|
| `GET /api/health` | none | `200 {"status":"ok"}`, no DB access (liveness) |
| `GET /api/health/ready` | none | `200 {"status":"ready","database":"ok"}`, or `503 {"status":"unavailable","database":"error"}`. No error details |
| `POST /api/auth/login` `{password}` | none + same-origin | 204 + `Set-Cookie`; 401 `{"detail":"invalid_credentials"}`; 429 when throttled |
| `POST /api/auth/logout` | session + same-origin | Revokes the session, clears the cookie, 204. Idempotent (204 with no session too) |
| `GET /api/auth/me` | session | `200 {"authenticated":true,"expires_at":…}`, or 401 |

- **Cookie:** `sb_session`, `HttpOnly`, `SameSite=Strict`, `Path=/api`, `Secure` from settings, `Max-Age` = TTL.
- **CSRF (`require_same_origin`)** for POST/PUT/PATCH/DELETE:
  - Accept when `Sec-Fetch-Site` is `same-origin`, or when `Origin` is in `SB_ALLOWED_ORIGINS`.
  - Reject with 403 `{"detail":"cross_origin"}` otherwise.
  - Requests carrying neither header are rejected, which keeps non-browser clients out until an API-token mechanism exists.
- **Errors:** all errors use FastAPI's `{"detail": <code>}` shape with stable snake_case codes. The password and cookie values are never logged. Log lines carry method, path, status and duration only.
- **OpenAPI:**
  - `create_app().openapi()` is exported by `ai-second-brain openapi` to stdout. Each route has an explicit `operation_id` (`health`, `ready`, `login`, `logout`, `me`), so generated names are stable.
  - The docs UI (`/api/docs`) is enabled only when `SB_ENV=dev`. `SB_ENV` is optional; it defaults to `dev` locally and is set to `prod` in deployment.

### 6.3 CLI (`ai-second-brain`, Typer)

- `serve [--reload] [--port]` runs uvicorn on `127.0.0.1`.
- `openapi [--output PATH]` writes the OpenAPI JSON to `PATH` (stdout by default). `--output` exists so just recipes need no shell redirects.
- `hash-password` prompts twice (hidden input) and prints an argon2 hash to paste into `.env`. It never writes files.

## 7. Web

**Dependencies:** react 19, react-dom, @tanstack/react-router (+ router plugin for Vite), @tanstack/react-query, openapi-fetch, tailwindcss v4 + @tailwindcss/vite, class-variance-authority, clsx, tailwind-merge, @radix-ui primitives (via shadcn/ui), lucide-react, sonner, @fontsource-variable/inter, @fontsource-variable/jetbrains-mono.
**Dev dependencies:** typescript, vite, @vitejs/plugin-react, @biomejs/biome, vitest, @testing-library/react, jsdom, @playwright/test, openapi-typescript, culori (contrast script), tsx.

- **tsconfig:** `strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`, `noImplicitOverride`, `verbatimModuleSyntax`. No `.js`/`.jsx` source files.
- **Vite:** dev server on 5173. `/api` is proxied to `http://127.0.0.1:${SB_API_PORT}`, so the browser sees one origin and the SameSite cookie works in dev.
- **API client:** `src/api/client.ts` creates an `openapi-fetch` client with `credentials: "same-origin"`. A 401 on any query other than `me` invalidates the session query, which makes the router redirect to `/login`.
- **Routing:**
  - `/login` is public. When already authenticated, it redirects to `/ask`.
  - The pathless `_app` layout's `beforeLoad` ensures the `me` query succeeds, otherwise it redirects to `/login?redirect=<path>`.
  - `/` redirects to `/ask`.
  - The 8 screens (`/ask`, `/search`, `/projects`, `/digest`, `/review`, `/nodes`, `/sources`, `/settings`) each render a placeholder card: the screen name, one sentence of purpose, and "Arrives in phase N" (Ask 1b, Search 2, Projects 8, Digest 4, Review 4, Nodes 5, Sources 2, Settings 1b).
- **AppShell:**
  - Left sidebar with nav links (lucide icons + labels, `aria-current` on the active item). On narrow viewports (< 768 px) it collapses to a bottom bar.
  - Header with the product name, theme toggle and Log out button.
  - The layout is keyboard navigable, and a skip-to-content link is present.
- **Login screen:** a password field (label "Password", `autocomplete="current-password"`) and a submit button that shows a pending state. Errors appear as an inline message with `role="alert"`: "Incorrect password", "Too many attempts, try again in N s", or "Can't reach the server". A successful login navigates to `redirect` or `/ask`.
- **Theme:** `ThemeProvider` stores `system | light | dark` in `localStorage` (wrapped in try/catch) and sets `data-theme` on `<html>`. System mode follows `prefers-color-scheme`.
- **tokens.css:** implements the three token layers from the design-system doc (palette in OKLCH, semantic, domain groups `tier`, `ingest`, `salience`, `node`, `link`) for both themes, exposed with Tailwind v4 `@theme`. Domain tokens are defined now even though 1a does not use them, so the contrast check covers them from the start.
- **Contrast check:** `scripts/check-contrast.ts` parses `tokens.css`, resolves each declared `-fg`/`-bg` pair per theme with culori, and fails below 4.5:1. Borders and icons against `bg`/`surface` must reach 3:1.
- **Hardcoded color guard:** `scripts/check-colors.ts` (run by `just web::check`) walks `src/`, skips `tokens.css`, and fails on hex/rgb/hsl/oklch literals or Tailwind arbitrary color classes (`-[#`). It is a TypeScript script rather than `grep`, so it behaves identically on Windows, macOS (BSD tools) and Linux (GNU tools).

## 8. just recipes

The root `justfile` uses `set dotenv-load`, `set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]`, and `mod backend`, `mod web`, `mod db`. On macOS and Linux, just uses its default `sh`.

**Cross-platform rule:** a recipe may have several lines, but every line is a single invocation of a cross-platform tool (`uv`, `pnpm`, `docker compose`, `git`, `dbmate`, `tsx`). No pipes, redirects to files, `&&` chains, globbing, or GNU/BSD/PowerShell-specific utilities (`sed`, `grep`, `test`, `Select-String`). Anything that needs logic or loops is a TypeScript script run with `tsx` (root `scripts/` or `web/scripts/`). `[windows]`/`[unix]`/`[macos]` recipe variants are not used; needing one is a signal to write a script. just's `{{ os() }}` is allowed only in messages.

| Recipe | Does |
|---|---|
| `setup` | `install`, then `db::up`, `db::wait`, `db::migrate`, `db::test-prepare`; prints next steps (hash password, `just dev`) |
| `install` | `uv sync --directory backend` + `pnpm install` (root workspace, includes web) + `pnpm --dir web exec playwright install chromium` |
| `dev` | `concurrently` with named, colored prefixes: `api` (`ai-second-brain serve --reload`) and `web` (`vite`). Requires the DB to be up (`db::up` runs first) |
| `check` | `backend::check` (ruff check, ruff format --check, pyright), `web::check` (biome ci, tsc --noEmit, contrast, color guard), `api-client-check`, `db::schema-check` |
| `test` | `backend::test` (all pytest tests, needs `TEST_DATABASE_URL`) + `web::test` (vitest run) |
| `test-unit` | `backend::test-unit` (`pytest -m "not integration"`, no database) + `web::test`. Used by the macOS CI job |
| `e2e` | `web::e2e`: Playwright against API + Vite started by Playwright's `webServer` config, using the test DB and a known test password hash from `.env.test` |
| `fmt` | ruff format + ruff check --fix, biome format --write |
| `api-client` | `ai-second-brain openapi --output web/src/api/openapi.json`, then `openapi-typescript` → `schema.d.ts` (two lines, no redirects) |
| `api-client-check` | `api-client`, then `git diff --exit-code web/src/api` |
| `hash-password` | `ai-second-brain hash-password` |
| `db::up` / `db::down` / `db::wait` | compose up -d / down / `tsx scripts/wait-for-db.ts`, which retries `docker compose exec -T postgres pg_isready` every second (30 s timeout) and prints OS-specific guidance when the Docker daemon is unreachable (Docker Desktop on Windows; Docker Desktop or OrbStack on macOS; the Docker service on Linux) |
| `db::migrate` / `db::status` / `db::rollback` / `db::new NAME` | dbmate via `pnpm exec dbmate` |
| `db::test-prepare` | create the test DB if missing (`dbmate -e TEST_DATABASE_URL create`), then migrate it |
| `db::reset` | drop + create + migrate the dev DB (asks for confirmation via `[confirm]`) |
| `db::schema-check` | `tsx scripts/schema-check.ts`: if `DATABASE_URL` is unreachable, prints `schema-check: SKIPPED (no database)` and exits 0; otherwise runs `dbmate dump` and fails when `git diff --exit-code db/schema.sql` shows changes |

`.env.test` (committed, test-only values) holds the e2e test password hash and the test DB URL. It contains no real secrets. The e2e password is `e2e-test-password`, documented as test-only.

## 9. Prerequisites and environment

- **Prerequisites** (documented in the README; `just setup` fails early with a clear message when one is missing): uv, just, Node ≥ 24 with pnpm (via corepack), and Docker with a running daemon. Python itself is provisioned by uv (3.12). dbmate comes from the pnpm workspace; no global install.
- **Supported development platforms:** Windows 11 (PowerShell 5.1), macOS on Apple Silicon (the owner's M1 MacBook Pro), and Linux (CI, Proxmox). All chosen tools and images ship native arm64 builds for macOS: uv-managed Python, the Node/pnpm packages, the dbmate npm binary, Playwright Chromium, and `pgvector/pgvector:pg17` (multi-arch amd64/arm64).
- **README install steps per OS:**

  | | Windows | macOS | Linux |
  |---|---|---|---|
  | uv, just | `winget install astral-sh.uv Casey.Just` | `brew install uv just` | official install scripts / distro packages |
  | Node 24 | `winget install OpenJS.NodeJS.LTS` or fnm | `brew install fnm && fnm install` (reads `.nvmrc`) | fnm / nvm |
  | pnpm | `corepack enable` | `corepack enable` | `corepack enable` |
  | Docker | Docker Desktop | Docker Desktop **or OrbStack** (lighter on M1) | Docker Engine |
- **Pins:**
  - `.python-version` 3.12.
  - `.nvmrc` 24, with `engines.node >=24`, so the local Node 25 is accepted.
  - The `packageManager` field pins the pnpm version installed at scaffold time.
  - The CI Node version is 24.
- **Line endings:** `.gitattributes` sets `* text=auto eol=lf`. `*.ps1` uses `eol=crlf` (not expected in 1a).

## 10. Testing

**Backend unit tests (no DB):**
- Password hash/verify round trip, including wrong-password and malformed-hash cases.
- Throttle lockout, `Retry-After` value and reset after success.
- Settings validation: a missing or invalid hash is rejected with the fix hint.
- The CSRF dependency's decision table: same-origin fetch site, allowed origin, disallowed origin, neither header, and safe methods passing without checks.

**Backend integration tests** (real Postgres at `TEST_DATABASE_URL`; each test truncates `auth_sessions`; every test in `tests/integration/` carries the `integration` pytest marker, registered in `pyproject.toml` with `--strict-markers`, so `pytest -m "not integration"` runs without a database):
- Login success sets the cookie with the expected attributes, and `me` returns 200.
- A wrong password returns 401 and creates no session row.
- Six rapid failures produce a 429.
- Logout revokes the session: its DB row is gone and `me` returns 401.
- An expired session is rejected and purged.
- `touch` extends the expiry but writes at most once per 5 minutes (time injected).
- Only the sha256 of the token is stored, never the raw token.
- `ready` returns 503 when the pool cannot connect (pool pointed at a closed port).

**Web unit tests (Vitest):**
- LoginForm: pending state, and each error message rendered with `role="alert"`.
- The theme toggle cycles through its modes and survives a throwing `localStorage`.
- The route guard redirects when `me` returns 401.

**E2E (Playwright, chromium):**
- Visiting `/ask` redirects to login.
- A wrong password shows the error.
- The correct password lands on `/ask` with the sidebar visible.
- The theme toggle switches `data-theme`.
- Logout returns to login.

**Static checks:** everything in `just check`.

## 11. CI (`.github/workflows/ci.yml`)

- **Trigger:** push and pull request to `main`.
- **Job `linux`** on `ubuntu-latest` (every push and PR):
  - Service `postgres: pgvector/pgvector:pg17` (user/password/db matching `.env.example`), health-checked.
  - Steps: checkout → `astral-sh/setup-uv` → `pnpm/action-setup` + `actions/setup-node` (node 24, pnpm cache) → `extractions/setup-just`.
  - Then: copy `.env.example` to `.env`, and set `SB_OWNER_PASSWORD_HASH` from `.env.test`.
  - Then: `just install`, `just db::migrate`, `just db::test-prepare`, `just check`, `just test`, `just e2e`.
- **Job `macos`** on `macos-latest` (Apple Silicon runner; push to `main` only, `if: github.event_name == 'push'`):
  - Same setup steps as `linux`, without the Postgres service (macOS runners have no Docker).
  - Then: `just install`, `just check` (with `db::schema-check` skipped when `DATABASE_URL` is unreachable; the script reports "skipped", not "passed"), `just test-unit`.
  - Purpose: catch macOS-specific breakage in tooling (paths, the case-insensitive default filesystem, BSD vs GNU behavior, arm64 packages) without paying for Docker-based tests.
- Playwright traces are uploaded on failure.
- No secrets are required.

## 12. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Recipes behave differently in PowerShell 5.1, macOS `sh` (BSD tools) and Linux `sh` (GNU tools) | Cross-platform rule (§8): single-tool recipe lines, with logic in `tsx` scripts. CI runs Ubuntu and macOS, and the owner runs Windows locally, so all three are exercised |
| macOS CI minutes are expensive (10× on private repos) | The macOS job runs only on push to `main`, not on pull requests, and skips Docker-dependent steps |
| GitHub macOS runners have no Docker | Integration and e2e tests run on Ubuntu only. The macOS job covers install, static checks and unit tests; the owner's M1 covers the Docker path manually (acceptance checklist) |
| The npm `dbmate` package cannot fetch its binary (offline/proxy) | Document the fallback: install dbmate via scoop/winget (Windows) or `brew install dbmate` (macOS), and set `DBMATE` in `.env` to override the command used by `db/justfile` |
| The Docker daemon is not running (current machine state) | `db::up` fails with "Start Docker Desktop" guidance |
| Generated client churn causes noisy diffs | Deterministic `operation_id`s; generation output formatted by Biome |
| SameSite=Strict cookie with the Vite proxy | Same origin via the proxy. The e2e test covers it |

## 13. Acceptance checklist

- [ ] Old MVP files removed. README describes the new setup in under 5 minutes of reading.
- [ ] `just setup` on the owner's Windows machine (Docker running) completes, and prints the next steps.
- [ ] `just dev` → browser login → shell with 8 placeholder screens, light/dark toggle, logout.
- [ ] `just check`, `just test` and `just e2e` pass locally.
- [ ] GitHub Actions workflow passes on the push to `main` (both `linux` and `macos` jobs).
- [ ] On the owner's M1 MacBook: `just setup`, `just dev` (login works in the browser), `just check` and `just test` pass.
- [ ] No recipe contains pipes, `&&`, redirects or OS-specific utilities (reviewed against the §8 rule).
- [ ] No hardcoded colors outside `tokens.css`; the contrast check passes for both themes.
- [ ] No secrets committed (`.env` ignored; `.env.test` has test-only values).

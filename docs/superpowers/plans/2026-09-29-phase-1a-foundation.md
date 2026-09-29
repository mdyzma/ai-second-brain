# Phase 1a Foundation Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the discarded MVP with a greenfield monorepo. It has a Python/FastAPI backend with single-user login, a React/TypeScript SPA shell with design tokens, dbmate migrations, and a root `justfile`. It must run on Windows, macOS (Apple Silicon) and Linux, with GitHub Actions CI.

**Architecture:**
- `backend/` is a uv project exposing a FastAPI app factory, an async psycopg pool, and argon2 + Postgres-backed sessions.
- `web/` is a Vite SPA that talks to `/api` through a client generated from the backend's OpenAPI schema.
- `db/` holds dbmate SQL migrations.
- Every command goes through `just`. Recipe lines are single cross-platform tool invocations; logic lives in `tsx` scripts.

**Tech Stack:** Python 3.12 (uv, FastAPI, uvicorn ≥ 0.54, psycopg 3 + psycopg_pool, argon2-cffi, Typer, pytest, ruff, pyright) · Node ≥ 24 (pnpm 12, TypeScript 5.9, Vite 8, React 19, TanStack Router/Query, Tailwind CSS 4, Biome 2, Vitest 5, Playwright, openapi-typescript/openapi-fetch, culori, tsx) · PostgreSQL 17 + pgvector (Docker `pgvector/pgvector:pg17`) · dbmate (npm) · just 1.58 · GitHub Actions.

**Spec:** [`docs/superpowers/specs/2026-09-29-phase-1a-foundation-design.md`](../specs/2026-09-29-phase-1a-foundation-design.md). Read it before starting. Parent docs: [`docs/architecture/`](../../architecture/README.md).

## Global Constraints

- Python **3.12** (`requires-python = ">=3.12"`, `.python-version` = `3.12`). **uv only. Never Poetry.**
- Node `>=24` (`.nvmrc` = `24`; the local Node 25 is fine). pnpm version pinned in `packageManager` (`pnpm@12.6.0`).
- TypeScript pinned to **`~5.9.3`** (openapi-typescript 7 peer-requires `^5.x`; do not install TypeScript 6/7).
- PostgreSQL 17 + pgvector via `pgvector/pgvector:pg17`, published on host port `127.0.0.1:5433` only (5432 is often taken by a native PostgreSQL install; container-internal port stays 5432).
- **Cross-platform recipe rule:** every `justfile` recipe line is one invocation of `uv`, `pnpm`, `docker`, `git`, `just` or `echo`. No pipes, `&&`, redirects (`>`), globbing, `sed`/`grep`/`test`/PowerShell cmdlets, and no `[windows]`/`[unix]` variants. Logic goes into TypeScript scripts run with `tsx`.
- Every `justfile` (root and modules) starts with `set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]`. The root one also has `set dotenv-load`.
- **Run `just` from the repository root.** Inside a subfolder, just picks up that folder's module `justfile` instead.
- Module recipes run with their module folder as the working directory, and they inherit the root `.env`.
- **Argon2 hashes in `.env` files must be single-quoted** (`SB_OWNER_PASSWORD_HASH='$argon2id$…'`). Verified: just's dotenv loader expands unquoted `$…` and corrupts the hash.
- The API binds to `127.0.0.1`. The session cookie is `sb_session`: `HttpOnly`, `SameSite=Strict`, `Path=/api`, `Max-Age` = TTL, `Secure` from settings.
- Errors are always `{"detail": "<snake_case_code>"}`. Codes: `invalid_credentials`, `too_many_attempts`, `not_authenticated`, `cross_origin`, `invalid_request`, `database_unavailable`.
- Operation IDs: `health`, `ready`, `login`, `logout`, `me`.
- Never log passwords, cookie values, tokens or request bodies. Log lines carry method, path, status and duration only.
- Components use semantic/domain tokens only. No color literals outside `web/src/design-system/tokens.css`.
- Placeholder phases: Ask 1b, Search 2, Projects 8, Digest 4, Review 4, Nodes 5, Sources 2, Settings 1b.
- **Commits:** directly on `main`. Conventional Commits: `type(scope): summary` header in imperative mood, ≤ 50 characters, no period; an optional body wrapped at 72 characters that explains what and why. Use the exact messages given in each task. **Never** add `Co-Authored-By`, "Generated with Claude Code" or any AI attribution. Do not push unless asked.

### Deliberate deviations from the spec (verified during planning)

| Spec says | Plan does | Why |
|---|---|---|
| `dbmate dump` writes `db/schema.sql`; CI uses a Postgres service container | `--no-dump-schema` on every dbmate call. `scripts/schema-check.ts` runs `pg_dump` **inside the compose container** and normalizes the output. CI Linux starts Postgres with `just db::up` (compose) | `pg_dump` is not installed on Windows (verified), and a runner's `pg_dump` can mismatch server 17. pg_dump 17.6+ emits random `\restrict` lines, which are stripped |
| Separate `db::up` and `db::wait` | `db::up` runs `scripts/db-up.ts`: Docker daemon check with per-OS guidance, then `docker compose up -d --wait` (healthcheck) | One recipe, same behavior; compose's `--wait` replaces the polling loop |
| pytest-asyncio in dev dependencies | Not used | Tests go through FastAPI `TestClient` plus sync psycopg for assertions |
| sonner (toasts) among the primitives | Not installed in 1a | No toast is needed yet (YAGNI); it arrives with the first feature that needs one |
| `web::check` generates nothing | Runs `tsr generate` (TanStack router CLI) before `tsc` | `tsc` needs `routeTree.gen.ts` to be current without starting Vite |
| `just setup` fails early with a clear message for every missing prerequisite | Clear per-OS message for Docker (`db-up.ts`). A missing `uv`/`pnpm`/`just` surfaces as the shell's "command not found" on the first recipe line, and the README lists the prerequisites | Checking for a missing pnpm would itself need pnpm/tsx. The shell error already names the missing tool |
| (not in the spec) | Adds `SB_WEB_PORT` (default 5173) | Lets e2e run Vite on 5174 next to a running dev server |

## Review Focus

These five input classes are implied by the spec but not named by it. Each has a pinned test in its owning task.

1. **Non-ASCII and whitespace-significant passwords** (Polish diacritics, emoji, trailing space) must round-trip exactly. A trimmed variant must fail. → Task 4 (`test_passwords.py`), Task 7 (`test_cli.py`).
2. **Oversized or malformed login bodies** (1 MB password, missing field, extra field, non-JSON) → 422 `{"detail":"invalid_request"}` quickly, without hashing and without counting as a failed attempt. → Task 6 (`test_auth_api.py`).
3. **Garbage session cookies** (empty, random string, 5 000 chars, a revoked token) → 401 `not_authenticated`, never a 500. → Task 6.
4. **Database unreachable while the API is up:** login, `me` and `ready` return 503 (`database_unavailable` or the ready body), not 500. The login page shows "Can't reach the server". → Task 5 (`test_health_api.py`), Task 6, Task 9 (`session.test.ts`).
5. **Open redirect via `/login?redirect=`** (`https://evil.example`, `//evil.example`, `/\evil.example`, `/login`) must fall back to `/ask`. → Task 9 (`session.test.ts`).

---

## File Structure

```
.gitattributes .gitignore .nvmrc .env.example .env.test
package.json pnpm-workspace.yaml justfile README.md
scripts/lib/docker.ts        # docker/compose helpers, daemon check + per-OS hint
scripts/init-env.ts          # create .env from .env.example if missing; warn if stale
scripts/db-up.ts             # daemon check, compose up --wait
scripts/schema-check.ts      # pg_dump in container → compare/write db/schema.sql
infra/compose.yaml
db/justfile  db/migrations/20260929000000_init.sql  db/schema.sql
backend/justfile backend/pyproject.toml backend/uv.lock backend/.python-version
backend/src/ai_second_brain/__init__.py
backend/src/ai_second_brain/config.py           # Settings, get_settings, HASH_HINT
backend/src/ai_second_brain/runtime.py          # selector event-loop factory (Windows + psycopg)
backend/src/ai_second_brain/db.py               # create_pool, ping
backend/src/ai_second_brain/auth/__init__.py
backend/src/ai_second_brain/auth/passwords.py   # hash_password, verify_password
backend/src/ai_second_brain/auth/throttle.py    # LoginThrottle
backend/src/ai_second_brain/auth/sessions.py    # Session, SessionStore, token_id, utc_now
backend/src/ai_second_brain/interfaces/__init__.py
backend/src/ai_second_brain/interfaces/api/__init__.py
backend/src/ai_second_brain/interfaces/api/app.py        # create_app, openapi_schema
backend/src/ai_second_brain/interfaces/api/schemas.py    # Pydantic API models
backend/src/ai_second_brain/interfaces/api/deps.py       # CSRF, session deps, cookie helpers
backend/src/ai_second_brain/interfaces/api/routes/__init__.py
backend/src/ai_second_brain/interfaces/api/routes/health.py
backend/src/ai_second_brain/interfaces/api/routes/auth.py
backend/src/ai_second_brain/interfaces/cli/__init__.py
backend/src/ai_second_brain/interfaces/cli/main.py       # Typer: serve, openapi, hash-password
backend/tests/conftest.py
backend/tests/unit/{test_config.py,test_runtime.py,test_passwords.py,test_throttle.py,test_csrf.py,test_health_api.py,test_cli.py}
backend/tests/integration/test_auth_api.py
web/justfile web/package.json web/tsconfig.json web/vite.config.ts web/biome.json web/playwright.config.ts web/index.html
web/scripts/{check-contrast.ts,check-contrast.test.ts,check-colors.ts,check-colors.test.ts}
web/src/main.tsx web/src/index.css web/src/routeTree.gen.ts (generated, committed) web/src/test/setup.ts
web/src/api/{openapi.json,schema.d.ts (generated),client.ts,client.test.ts}
web/src/design-system/{tokens.css,cn.ts,theme.tsx,theme.test.tsx,AppShell.tsx}
web/src/design-system/ui/{button.tsx,input.tsx,label.tsx,card.tsx}
web/src/features/auth/{session.ts,session.test.ts,guard.ts,guard.test.ts,LoginForm.tsx,LoginForm.test.tsx}
web/src/features/screens/{screens.ts,PlaceholderScreen.tsx}
web/src/routes/{__root.tsx,index.tsx,login.tsx,_app.tsx}
web/src/routes/_app/{ask,search,projects,digest,review,nodes,sources,settings}.tsx
web/tests/e2e/auth.spec.ts
.github/workflows/ci.yml       # + release job (Task 13)
.releaserc.json scripts/set-version.ts scripts/lib/version.ts scripts/lib/version.test.ts  # Task 13
```

---

### Task 1: Repository reset and root workspace

Removes the MVP and sets up the root tooling that every later task uses.

**Files:**
- Delete: `src/`, `tools/`, `tests/`, `sql_migrations/`, `docker-compose.yml`, `pyproject.toml`, `uv.lock`, `.python-version` (root), `.venv/`, `.pytest_cache/`, `.ruff_cache/`
- Create: `.gitattributes`, `.nvmrc`, `.env.example`, `.env.test`, `package.json`, `pnpm-workspace.yaml`, `scripts/lib/docker.ts`, `scripts/init-env.ts`
- Modify (overwrite): `.gitignore`, `justfile`

**Interfaces:**
- Produces: `scripts/lib/docker.ts` exports `repoRoot: string`, `composeFile: string`, `docker(args: string[]): SpawnSyncReturns<string>`, `compose(args: string[]): SpawnSyncReturns<string>`, `dockerAvailable(): boolean`, `dockerHint(os?: NodeJS.Platform): string`. Root `justfile` with `default` and `install`. Env variable names used everywhere (table in spec §4).

- [ ] **Step 1: Delete the MVP**

```bash
git rm -r -q src tools tests sql_migrations docker-compose.yml pyproject.toml uv.lock .python-version
```

Then delete the untracked build leftovers (`.venv/`, `.pytest_cache/`, `.ruff_cache/`) at the repo root. In PowerShell:

```powershell
Remove-Item -Recurse -Force .venv, .pytest_cache, .ruff_cache -ErrorAction SilentlyContinue
```

On macOS/Linux:

```bash
rm -rf .venv .pytest_cache .ruff_cache
```

- [ ] **Step 2: Write `.gitignore`**

```gitignore
# OS / editors
.DS_Store
.idea/
.vscode/
.claude/

# Environment (never commit real secrets; .env.test is test-only and committed)
.env

# Python
__pycache__/
*.py[cod]
.venv/
.pytest_cache/
.ruff_cache/
.coverage
htmlcov/

# Node / web
node_modules/
web/dist/
web/test-results/
web/playwright-report/
*.tsbuildinfo
```

- [ ] **Step 3: Write `.gitattributes` and `.nvmrc`**

`.gitattributes`:

```gitattributes
* text=auto eol=lf
*.ps1 text eol=crlf
*.png binary
*.jpg binary
*.woff2 binary
```

`.nvmrc`:

```
24
```

- [ ] **Step 4: Renormalize line endings**

Run: `git add --renormalize .`
Expected: no output; `git status` shows only the files you changed or deleted. This stops the LF/CRLF warnings on every commit.

- [ ] **Step 5: Write `.env.example`**

```dotenv
# Copy to .env (just setup does this for you). Never commit .env.
# Database shared by dbmate and the backend (dev container from infra/compose.yaml)
DATABASE_URL=postgres://brain:brain@localhost:5433/ai_second_brain?sslmode=disable
# Test database used by pytest and e2e (created by `just db::test-prepare`)
TEST_DATABASE_URL=postgres://brain:brain@localhost:5433/ai_second_brain_test?sslmode=disable

# Owner login. Run `just hash-password` and paste the printed line here.
# KEEP THE SINGLE QUOTES: unquoted '$' characters are expanded by just's .env loader.
SB_OWNER_PASSWORD_HASH=''
SB_SESSION_TTL_DAYS=14
SB_COOKIE_SECURE=false
SB_ALLOWED_ORIGINS=http://localhost:5173
SB_API_PORT=8000
SB_WEB_PORT=5173
# dev enables /api/docs; prod disables it
SB_ENV=dev
# Optional: use a globally installed dbmate instead of the npm one (scoop/winget/brew)
# DBMATE=dbmate
```

- [ ] **Step 6: Write `.env.test`** (committed on purpose; test-only values)

```dotenv
# TEST-ONLY VALUES, committed on purpose. Not secrets.
# The e2e owner password is: e2e-test-password
TEST_DATABASE_URL=postgres://brain:brain@localhost:5433/ai_second_brain_test?sslmode=disable
SB_OWNER_PASSWORD_HASH='$argon2id$v=19$m=65536,t=3,p=4$lUbERLF2lShFt/g2zuyNHw$/2JZ1Uy+8w4nXWGCR1KY0IwYFD1CnGSOM7cAtbhtC/w'
SB_API_PORT=8001
SB_WEB_PORT=5174
```

- [ ] **Step 7: Write root `package.json` and `pnpm-workspace.yaml`**

`package.json`:

```json
{
  "name": "ai-second-brain-workspace",
  "private": true,
  "type": "module",
  "packageManager": "pnpm@12.6.0",
  "engines": {
    "node": ">=24"
  }
}
```

`pnpm-workspace.yaml` (pnpm 12 **fails** installs whose build scripts are not approved. This list is the toolchain allowlist):

```yaml
packages:
  - web

allowBuilds:
  esbuild: true
  "@tailwindcss/oxide": true
  "@parcel/watcher": true
```

If a later `pnpm install`/`pnpm add` fails with `ERR_PNPM_IGNORED_BUILDS` for another **toolchain** package (a bundler, formatter or native binary), add it here as `true` and re-run. Never allow build scripts for runtime UI libraries.

- [ ] **Step 8: Install root tools**

Run: `pnpm add -D -w dbmate tsx concurrently`
Expected: `+ dbmate 2.x`, `+ tsx 4.x`, `+ concurrently 10.x`.
Then run: `pnpm exec dbmate --version`
Expected: `dbmate version 2.…`

- [ ] **Step 9: Write `scripts/lib/docker.ts`**

```ts
import { type SpawnSyncReturns, spawnSync } from "node:child_process";
import { platform } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
export const composeFile = join(repoRoot, "infra", "compose.yaml");

export function docker(args: string[]): SpawnSyncReturns<string> {
  return spawnSync("docker", args, { encoding: "utf8" });
}

export function compose(args: string[]): SpawnSyncReturns<string> {
  return docker(["compose", "-f", composeFile, ...args]);
}

/** True when the docker CLI exists and the daemon answers. */
export function dockerAvailable(): boolean {
  const result = docker(["info", "--format", "{{.ServerVersion}}"]);
  return result.error === undefined && result.status === 0;
}

export function dockerHint(os: NodeJS.Platform = platform()): string {
  switch (os) {
    case "win32":
      return "Start Docker Desktop and wait until it reports 'Engine running'.";
    case "darwin":
      return "Start Docker Desktop or OrbStack, then retry.";
    default:
      return "Start the Docker service (e.g. `sudo systemctl start docker`), then retry.";
  }
}
```

- [ ] **Step 10: Write `scripts/init-env.ts`**

```ts
import { copyFileSync, existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { parseEnv } from "node:util";
import { repoRoot } from "./lib/docker.ts";

const envPath = join(repoRoot, ".env");
const examplePath = join(repoRoot, ".env.example");

if (!existsSync(envPath)) {
  copyFileSync(examplePath, envPath);
  console.log("Created .env from .env.example.");
} else {
  const current = parseEnv(readFileSync(envPath, "utf8"));
  const expected = Object.keys(parseEnv(readFileSync(examplePath, "utf8")));
  const missing = expected.filter((key) => !(key in current));
  if (missing.length > 0) {
    console.warn(`.env is missing: ${missing.join(", ")}. Copy them from .env.example.`);
  }
}
```

- [ ] **Step 11: Write the root `justfile`** (the first version; later tasks add recipes)

```just
set dotenv-load
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

# List all recipes
default:
    @just --list --list-submodules

# Install JavaScript tooling (Python and web are added in later tasks)
install:
    pnpm install
```

- [ ] **Step 12: Verify**

Run: `just --list`
Expected: shows `default` and `install` with no errors.
Run: `pnpm exec tsx scripts/init-env.ts`
Expected: `Created .env from .env.example.` Run it a second time: no output.

- [ ] **Step 13: Commit**

```bash
git add -A
git commit -m "chore: remove MVP and add root workspace tooling"
```

---

### Task 2: Database — compose, migration, dbmate recipes, schema check

**Files:**
- Create: `infra/compose.yaml`, `db/migrations/20260929000000_init.sql`, `db/justfile`, `scripts/db-up.ts`, `scripts/schema-check.ts`, `db/schema.sql` (generated)
- Modify: `justfile` (add `mod db`)

**Interfaces:**
- Consumes: `scripts/lib/docker.ts` (Task 1).
- Produces: recipes `db::up`, `db::down`, `db::migrate`, `db::status`, `db::rollback`, `db::new NAME`, `db::test-prepare`, `db::reset`, `db::dump`, `db::schema-check`. Table `auth_sessions(id bytea pk, created_at, last_seen_at, expires_at timestamptz, user_agent text)`. Compose service name `postgres`, user/password `brain`, db `ai_second_brain`.

- [ ] **Step 1: Write `infra/compose.yaml`**

```yaml
name: ai-second-brain

services:
  postgres:
    image: pgvector/pgvector:pg17
    environment:
      POSTGRES_USER: brain
      POSTGRES_PASSWORD: brain
      POSTGRES_DB: ai_second_brain
    ports:
      - "127.0.0.1:5433:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U brain -d ai_second_brain"]
      interval: 2s
      timeout: 3s
      retries: 30

volumes:
  pgdata:
```

- [ ] **Step 2: Write the migration `db/migrations/20260929000000_init.sql`**

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

- [ ] **Step 3: Write `scripts/db-up.ts`**

```ts
import { compose, dockerAvailable, dockerHint } from "./lib/docker.ts";

if (!dockerAvailable()) {
  console.error(`Docker is not reachable. ${dockerHint()}`);
  process.exit(1);
}

const result = compose(["up", "-d", "--wait", "--wait-timeout", "60"]);
process.stdout.write(result.stdout ?? "");
process.stderr.write(result.stderr ?? "");
if (result.status !== 0) {
  console.error("Postgres did not become healthy. Inspect: docker compose -f infra/compose.yaml logs postgres");
  process.exit(result.status ?? 1);
}
console.log("Postgres is up (127.0.0.1:5433).");
```

- [ ] **Step 4: Write `scripts/schema-check.ts`**

```ts
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { compose, dockerAvailable, repoRoot } from "./lib/docker.ts";

const schemaPath = join(repoRoot, "db", "schema.sql");
const write = process.argv.includes("--write");
const HEADER = "-- Generated by `just db::dump` (pg_dump --schema-only in the compose container). Do not edit.\n";

/** Remove nondeterministic lines (pg_dump 17.6+ \restrict keys, version banners). */
export function normalize(dump: string): string {
  const lines = dump
    .replace(/\r\n/g, "\n")
    .split("\n")
    .filter((line) => !/^\\(un)?restrict\b/.test(line) && !/^-- Dumped (from|by)\b/.test(line));
  return `${HEADER}${lines.join("\n").replace(/\n{3,}/g, "\n\n").trim()}\n`;
}

const ready = dockerAvailable()
  ? compose(["exec", "-T", "postgres", "pg_isready", "-U", "brain", "-d", "ai_second_brain"])
  : undefined;
if (ready === undefined || ready.status !== 0) {
  console.log("schema-check: SKIPPED (no database)");
  process.exit(0);
}

const dump = compose([
  "exec", "-T", "postgres", "pg_dump", "--schema-only", "--no-owner", "--no-privileges",
  "--exclude-table=public.schema_migrations", "-U", "brain", "ai_second_brain",
]);
if (dump.status !== 0) {
  console.error(dump.stderr);
  process.exit(1);
}
const fresh = normalize(dump.stdout);

if (write) {
  writeFileSync(schemaPath, fresh, "utf8");
  console.log("db/schema.sql written.");
  process.exit(0);
}

let committed = "";
try {
  committed = readFileSync(schemaPath, "utf8").replace(/\r\n/g, "\n");
} catch {
  committed = "";
}
if (committed !== fresh) {
  console.error("db/schema.sql is out of date. Run `just db::dump` and commit it.");
  process.exit(1);
}
console.log("schema-check: OK");
```

- [ ] **Step 5: Write `db/justfile`**

```just
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

root := parent_directory(source_directory())
compose_file := root / "infra" / "compose.yaml"
# DBMATE in .env overrides the npm binary (fallback when it can't be downloaded), e.g. DBMATE=dbmate
dbmate_bin := env("DBMATE", "pnpm --dir " + quote(root) + " exec dbmate")
dbmate := dbmate_bin + " --migrations-dir " + quote(root / "db" / "migrations") + " --no-dump-schema"

# Start the dev Postgres container (checks Docker first)
up:
    pnpm --dir {{ quote(root) }} exec tsx scripts/db-up.ts

# Stop the dev Postgres container (data is kept in the volume)
down:
    docker compose -f {{ quote(compose_file) }} down

# Create the dev database if needed and apply migrations
migrate:
    {{ dbmate }} up

# Show applied and pending migrations
status:
    {{ dbmate }} status

# Roll back the most recent migration
rollback:
    {{ dbmate }} rollback

# Create a new migration file: just db::new add_things
new name:
    {{ dbmate }} new {{ name }}

# Create and migrate the test database (TEST_DATABASE_URL)
test-prepare:
    {{ dbmate }} --env TEST_DATABASE_URL up

# Drop, recreate and migrate the dev database
[confirm("Drop and recreate the dev database? All local data will be lost.")]
reset:
    {{ dbmate }} drop
    {{ dbmate }} up

# Regenerate db/schema.sql from the dev database
dump:
    pnpm --dir {{ quote(root) }} exec tsx scripts/schema-check.ts --write

# Fail if db/schema.sql is stale (skips when no database)
schema-check:
    pnpm --dir {{ quote(root) }} exec tsx scripts/schema-check.ts
```

- [ ] **Step 6: Register the module.** Add `mod db` to the root `justfile` below the `set` lines:

```just
set dotenv-load
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

mod db
```

- [ ] **Step 7: Verify the whole database path** (Docker must be running)

Run: `just db::up`
Expected: `Postgres is up (127.0.0.1:5433).` With Docker stopped, you get the per-OS hint and exit 1. Check that path once.
Run: `just db::migrate`
Expected: `Applying: 20260929000000_init.sql`.
Run: `just db::test-prepare`
Expected: it creates `ai_second_brain_test` and applies the migration.
Run: `just db::status`
Expected: `[X] 20260929000000_init.sql`, `Applied: 1`, `Pending: 0`.
Run: `just db::schema-check`
Expected: FAIL with `db/schema.sql is out of date` (the file doesn't exist yet).
Run: `just db::dump` then `just db::schema-check`
Expected: `db/schema.sql written.` then `schema-check: OK`. Open `db/schema.sql` and confirm it contains `CREATE EXTENSION IF NOT EXISTS vector`, `CREATE TABLE public.auth_sessions` and no `\restrict` line.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(db): add pgvector compose service, init migration and dbmate recipes"
```

---

### Task 3: Backend project and configuration

**Files:**
- Create: `backend/pyproject.toml`, `backend/.python-version`, `backend/justfile`, `backend/src/ai_second_brain/__init__.py`, `backend/src/ai_second_brain/config.py`, `backend/src/ai_second_brain/runtime.py`, `backend/tests/conftest.py`, `backend/tests/unit/test_config.py`, `backend/tests/unit/test_runtime.py`
- Modify: root `justfile` (`mod backend`, `install` gains `uv sync`)

**Interfaces:**
- Produces:
  - `ai_second_brain.config`: `Settings` (fields `database_url` alias `DATABASE_URL`, `owner_password_hash`, `session_ttl_days`, `cookie_secure`, `allowed_origins`, `api_port`, `env`; property `allowed_origin_set: frozenset[str]`), `get_settings() -> Settings`, `HASH_HINT: str`, `REPO_ROOT: Path`, `ENV_FILE: Path`.
  - `ai_second_brain.runtime`: `new_event_loop() -> asyncio.AbstractEventLoop`.
  - Test fixtures in `conftest.py`: `make_settings(**overrides) -> Settings`, `TEST_PASSWORD`, `TEST_HASH`, `SAME_ORIGIN` headers.

- [ ] **Step 1: Create the uv project files**

`backend/.python-version`:

```
3.12
```

`backend/pyproject.toml`:

```toml
[project]
name = "ai-second-brain"
version = "0.2.0"
description = "Private-by-default personal knowledge system: backend API, worker and admin CLI"
requires-python = ">=3.12"
dependencies = []

[project.scripts]
ai-second-brain = "ai_second_brain.interfaces.cli.main:app"

[dependency-groups]
dev = []

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP", "B", "S", "ASYNC"]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101", "S105", "S106"]

[tool.pyright]
include = ["src", "tests"]
pythonVersion = "3.12"
typeCheckingMode = "standard"
venvPath = "."
venv = ".venv"

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = ["--strict-markers"]
markers = ["integration: needs PostgreSQL at TEST_DATABASE_URL (run via `just test`)"]

[build-system]
requires = ["uv_build>=0.12,<0.13"]
build-backend = "uv_build"
```

- [ ] **Step 2: Write `backend/src/ai_second_brain/__init__.py`** (uv builds the package during `uv add`, so the module must exist first)

```python
"""Second Brain backend."""
```

- [ ] **Step 3: Add dependencies with uv** (run from the repo root)

```bash
uv add --directory backend "fastapi>=0.118" "uvicorn[standard]>=0.54" "pydantic-settings>=2.7" "psycopg[binary,pool]>=3.2" "argon2-cffi>=23.1" "typer>=0.15"
uv add --directory backend --group dev "pytest>=8.3" "httpx>=0.28" "ruff>=0.15" "pyright>=1.1.400"
```

Expected: `backend/uv.lock` is created, and `backend/.venv` holds Python 3.12. `uvicorn` must resolve to ≥ 0.54, because the custom loop factory below depends on it.

- [ ] **Step 4: Write the failing tests `backend/tests/conftest.py` and `backend/tests/unit/test_config.py`**

`backend/tests/conftest.py`:

```python
from collections.abc import Callable
from typing import Any

import pytest

from ai_second_brain.auth.passwords import hash_password
from ai_second_brain.config import Settings

TEST_PASSWORD = "correct horse battery staple"
TEST_HASH = hash_password(TEST_PASSWORD)
SAME_ORIGIN = {"Sec-Fetch-Site": "same-origin"}
UNUSED_DB = "postgres://brain:brain@127.0.0.1:1/unused?connect_timeout=1"


@pytest.fixture
def make_settings() -> Callable[..., Settings]:
    def _make(**overrides: Any) -> Settings:
        values: dict[str, Any] = {
            "DATABASE_URL": UNUSED_DB,
            "owner_password_hash": TEST_HASH,
            "allowed_origins": "http://localhost:5173",
        }
        values.update(overrides)
        return Settings(_env_file=None, **values)  # pyright: ignore[reportCallIssue]

    return _make
```

`conftest.py` imports `ai_second_brain.auth.passwords`, which Task 4 creates. Create the minimal module now so the imports resolve. Task 4 replaces it with the real, tested implementation:

`backend/src/ai_second_brain/auth/__init__.py`:

```python
"""Authentication: password hashing, login throttling, sessions."""
```

`backend/src/ai_second_brain/auth/passwords.py`:

```python
from argon2 import PasswordHasher

_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)
```

`backend/tests/unit/test_config.py`:

```python
from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_second_brain.config import ENV_FILE, REPO_ROOT, Settings

from ..conftest import TEST_HASH

ENV_VARS = [
    "DATABASE_URL", "TEST_DATABASE_URL", "SB_OWNER_PASSWORD_HASH", "SB_SESSION_TTL_DAYS",
    "SB_COOKIE_SECURE", "SB_ALLOWED_ORIGINS", "SB_API_PORT", "SB_ENV",
]


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_env_file_is_repository_root_env() -> None:
    assert REPO_ROOT / ".env" == ENV_FILE
    assert (REPO_ROOT / "backend" / "pyproject.toml").is_file()


def test_defaults(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings()
    assert settings.session_ttl_days == 14
    assert settings.cookie_secure is False
    assert settings.env == "dev"
    assert settings.api_port == 8000


@pytest.mark.parametrize("bad", ["", "plain-text", "=19=65536,t=3,p=4"])
def test_rejects_missing_or_corrupted_hash(
    make_settings: Callable[..., Settings], bad: str
) -> None:
    with pytest.raises(ValidationError) as excinfo:
        make_settings(owner_password_hash=bad)
    message = str(excinfo.value)
    assert "just hash-password" in message
    assert "single quotes" in message


@pytest.mark.usefixtures("clean_env")
def test_missing_hash_is_rejected_even_when_not_passed() -> None:
    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None, DATABASE_URL="postgres://u:p@localhost/db")  # pyright: ignore[reportCallIssue]
    assert "just hash-password" in str(excinfo.value)


def test_rejects_unknown_env(make_settings: Callable[..., Settings]) -> None:
    with pytest.raises(ValidationError):
        make_settings(env="staging")


def test_allowed_origin_set_trims_and_drops_trailing_slash(
    make_settings: Callable[..., Settings],
) -> None:
    settings = make_settings(allowed_origins=" http://localhost:5173/ ,http://brain.lan ,, ")
    assert settings.allowed_origin_set == frozenset({"http://localhost:5173", "http://brain.lan"})


@pytest.mark.usefixtures("clean_env")
def test_reads_single_quoted_hash_from_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DATABASE_URL=postgres://u:p@localhost:5432/db\n"
        f"SB_OWNER_PASSWORD_HASH='{TEST_HASH}'\n"
        "SB_ENV=prod\n",
        encoding="utf-8",
    )
    settings = Settings(_env_file=env_file)  # pyright: ignore[reportCallIssue]
    assert settings.owner_password_hash == TEST_HASH
    assert settings.database_url == "postgres://u:p@localhost:5432/db"
    assert settings.env == "prod"
```

Also create empty `backend/tests/__init__.py` and `backend/tests/unit/__init__.py` so the relative `from ..conftest import …` works.

- [ ] **Step 5: Run the tests to verify they fail**

Run: `uv run --directory backend pytest tests/unit/test_config.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ai_second_brain.config'`.

- [ ] **Step 6: Write `backend/src/ai_second_brain/config.py`**

```python
"""Settings from the environment and the repository-root .env file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = REPO_ROOT / ".env"

HASH_HINT = (
    "Run `just hash-password` and paste the printed line into .env. "
    "Keep the single quotes: unquoted '$' characters are expanded by just's .env loader."
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SB_",
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    database_url: str = Field(validation_alias="DATABASE_URL")
    owner_password_hash: str = Field(default="", validate_default=True)
    session_ttl_days: int = Field(default=14, ge=1, le=365)
    cookie_secure: bool = False
    allowed_origins: str = "http://localhost:5173"
    api_port: int = 8000
    env: Literal["dev", "prod"] = "dev"

    @field_validator("owner_password_hash")
    @classmethod
    def _must_be_argon2(cls, value: str) -> str:
        if not value.startswith("$argon2"):
            raise ValueError(
                f"SB_OWNER_PASSWORD_HASH is missing or not an argon2 hash. {HASH_HINT}"
            )
        return value

    @property
    def allowed_origin_set(self) -> frozenset[str]:
        parts = (origin.strip().rstrip("/") for origin in self.allowed_origins.split(","))
        return frozenset(origin for origin in parts if origin)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue]
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run --directory backend pytest tests/unit/test_config.py -q`
Expected: `8 passed` (the parametrized hash test counts 3).

- [ ] **Step 8: Write the failing test `backend/tests/unit/test_runtime.py`**

```python
import asyncio

from ai_second_brain.runtime import new_event_loop


def test_new_event_loop_is_a_selector_loop() -> None:
    loop = new_event_loop()
    try:
        assert isinstance(loop, asyncio.SelectorEventLoop)
    finally:
        loop.close()
```

Run: `uv run --directory backend pytest tests/unit/test_runtime.py -q`
Expected: FAIL, `No module named 'ai_second_brain.runtime'`.

- [ ] **Step 9: Write `backend/src/ai_second_brain/runtime.py`**

```python
"""Event loop factory for uvicorn (`loop="ai_second_brain.runtime:new_event_loop"`).

psycopg's async mode needs a selector event loop. On Windows, asyncio and uvicorn otherwise
use the Proactor loop. macOS and Linux already default to selector loops.
"""

import asyncio


def new_event_loop() -> asyncio.AbstractEventLoop:
    return asyncio.SelectorEventLoop()
```

Run: `uv run --directory backend pytest tests/unit -q`
Expected: all pass.

- [ ] **Step 10: Write `backend/justfile` and register it**

`backend/justfile`:

```just
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

# Install backend dependencies into backend/.venv
sync:
    uv sync

# Lint, format check and type check
check:
    uv run ruff check .
    uv run ruff format --check .
    uv run pyright

# All tests (integration tests need TEST_DATABASE_URL)
test *args:
    uv run pytest {{ args }}

# Tests that need no database
test-unit *args:
    uv run pytest -m "not integration" {{ args }}

# Format and auto-fix
fmt:
    uv run ruff format .
    uv run ruff check --fix .
```

Root `justfile`: add `mod backend` next to `mod db`, and make `install` sync Python too:

```just
mod backend
mod db

# Install Python and JavaScript dependencies
install:
    uv sync --directory backend
    pnpm install
```

- [ ] **Step 11: Verify static checks**

Run: `just backend::check`
Expected: ruff reports no errors, `ruff format --check` reports all files formatted (run `just backend::fmt` first if not), and pyright shows `0 errors`. The first pyright run downloads its Node package, which is expected.

- [ ] **Step 12: Commit**

```bash
git add -A
git commit -m "feat(backend): add uv project, settings and selector loop factory"
```

---

### Task 4: Password hashing and login throttle

**Files:**
- Modify: `backend/src/ai_second_brain/auth/passwords.py`
- Create: `backend/src/ai_second_brain/auth/throttle.py`, `backend/tests/unit/test_passwords.py`, `backend/tests/unit/test_throttle.py`

**Interfaces:**
- Produces:
  - `passwords.hash_password(plain: str) -> str` and `passwords.verify_password(password_hash: str, plain: str) -> bool` (never raises).
  - `throttle.LoginThrottle(max_failures: int = 5, lockout_seconds: float = 60, clock: Callable[[], float] = time.monotonic)` with `retry_after() -> int | None`, `record_failure() -> None`, `record_success() -> None`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/unit/test_passwords.py`:

```python
import pytest

from ai_second_brain.auth.passwords import hash_password, verify_password

POLISH = "zażółć gęślą jaźń 🔑 "  # trailing space is part of the password


def test_round_trip() -> None:
    hashed = hash_password("s3cret")
    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "s3cret")


def test_wrong_password_is_false() -> None:
    assert not verify_password(hash_password("s3cret"), "S3cret")


def test_non_ascii_and_whitespace_are_significant() -> None:
    hashed = hash_password(POLISH)
    assert verify_password(hashed, POLISH)
    assert not verify_password(hashed, POLISH.strip())
    assert not verify_password(hashed, "zazolc gesla jazn 🔑 ")


@pytest.mark.parametrize("bad_hash", ["", "not-a-hash", "$argon2id$v=19$broken"])
def test_malformed_hash_is_false_not_error(bad_hash: str) -> None:
    assert verify_password(bad_hash, "anything") is False


def test_hashes_are_salted() -> None:
    assert hash_password("same") != hash_password("same")
```

`backend/tests/unit/test_throttle.py`:

```python
from ai_second_brain.auth.throttle import LoginThrottle


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_allows_until_limit_then_locks() -> None:
    clock = FakeClock()
    throttle = LoginThrottle(max_failures=5, lockout_seconds=60, clock=clock)
    for _ in range(4):
        throttle.record_failure()
        assert throttle.retry_after() is None
    throttle.record_failure()
    assert throttle.retry_after() == 60


def test_retry_after_counts_down_and_rounds_up() -> None:
    clock = FakeClock()
    throttle = LoginThrottle(max_failures=1, lockout_seconds=60, clock=clock)
    throttle.record_failure()
    clock.now += 59.2
    assert throttle.retry_after() == 1


def test_lock_expires_and_counter_resets() -> None:
    clock = FakeClock()
    throttle = LoginThrottle(max_failures=2, lockout_seconds=60, clock=clock)
    throttle.record_failure()
    throttle.record_failure()
    clock.now += 60
    assert throttle.retry_after() is None
    throttle.record_failure()
    assert throttle.retry_after() is None  # one failure after reset is below the limit


def test_success_resets() -> None:
    clock = FakeClock()
    throttle = LoginThrottle(max_failures=2, lockout_seconds=60, clock=clock)
    throttle.record_failure()
    throttle.record_success()
    throttle.record_failure()
    assert throttle.retry_after() is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --directory backend pytest tests/unit/test_passwords.py tests/unit/test_throttle.py -q`
Expected: FAIL. `verify_password` and `ai_second_brain.auth.throttle` can't be imported.

- [ ] **Step 3: Implement**

`backend/src/ai_second_brain/auth/passwords.py`:

```python
"""Argon2id password hashing for the single owner account."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(password_hash: str, plain: str) -> bool:
    """True only for a correct password. Mismatches and malformed hashes return False."""
    try:
        return _hasher.verify(password_hash, plain)
    except (VerificationError, InvalidHashError):
        return False
```

`backend/src/ai_second_brain/auth/throttle.py`:

```python
"""In-process login throttle.

State lives in this process only. That is acceptable because the API is single-user and
single-process (spec §6.1). After ``max_failures`` consecutive failures, logins are refused
for ``lockout_seconds``. A success resets the counter.
"""

import math
import time
from collections.abc import Callable


class LoginThrottle:
    def __init__(
        self,
        max_failures: int = 5,
        lockout_seconds: float = 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_failures = max_failures
        self._lockout_seconds = lockout_seconds
        self._clock = clock
        self._failures = 0
        self._locked_until: float | None = None

    def retry_after(self) -> int | None:
        """Whole seconds until the next attempt is allowed, or None when not locked."""
        if self._locked_until is None:
            return None
        remaining = self._locked_until - self._clock()
        if remaining <= 0:
            self._locked_until = None
            self._failures = 0
            return None
        return max(1, math.ceil(remaining))

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._max_failures:
            self._locked_until = self._clock() + self._lockout_seconds

    def record_success(self) -> None:
        self._failures = 0
        self._locked_until = None
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run --directory backend pytest tests/unit -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(auth): add argon2 verify and login throttle"
```

---

### Task 5: Database pool, app factory and health endpoints

**Files:**
- Create: `backend/src/ai_second_brain/db.py`, `backend/src/ai_second_brain/interfaces/__init__.py`, `backend/src/ai_second_brain/interfaces/api/__init__.py`, `backend/src/ai_second_brain/interfaces/api/schemas.py`, `backend/src/ai_second_brain/interfaces/api/app.py`, `backend/src/ai_second_brain/interfaces/api/routes/__init__.py`, `backend/src/ai_second_brain/interfaces/api/routes/health.py`, `backend/tests/unit/test_health_api.py`

**Interfaces:**
- Consumes: `Settings` (Task 3).
- Produces:
  - `db.create_pool(database_url: str) -> AsyncConnectionPool` and `db.ping(pool, timeout: float = 2.0) -> bool`.
  - `app.create_app(settings: Settings | None = None, *, clock: Callable[[], datetime] = utc_now, throttle_clock: Callable[[], float] = time.monotonic) -> FastAPI` and `app.openapi_schema() -> dict[str, Any]`.
  - `app.state` holds `settings`, `pool`, `sessions` (Task 6 wires this) and `throttle`.
  - `schemas` defines `HealthResponse`, `ReadyResponse`, `ErrorResponse`, `LoginRequest` and `MeResponse`.
  - Logger name: `ai_second_brain.api`.
  - Test helper `make_client(app) -> TestClient` in `tests/conftest.py` (selector loop). All later API tests use it instead of a bare `TestClient`.

> Task 6 adds `SessionStore`. To keep this task self-contained, `create_app` here does not construct sessions yet. Task 6 adds that code to the lifespan.

- [ ] **Step 1: Add a selector-loop `TestClient` helper to `backend/tests/conftest.py`**

psycopg's async mode cannot run on Windows' default Proactor loop, and `TestClient` runs the app on an anyio event loop. Pass the loop factory explicitly so tests behave the same on every OS. Add to `conftest.py` (imports go with the other imports so ruff's import sorting passes):

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_second_brain.runtime import new_event_loop


def make_client(app: FastAPI) -> TestClient:
    """TestClient on a selector event loop (required by psycopg async on Windows)."""
    return TestClient(app, backend_options={"loop_factory": new_event_loop})
```

- [ ] **Step 2: Write the failing tests `backend/tests/unit/test_health_api.py`**

These need **no** database. They point the app at a closed port to exercise the "database down" path (Review Focus 4).

```python
from collections.abc import Callable

from ai_second_brain.config import Settings
from ai_second_brain.interfaces.api.app import create_app, openapi_schema

from ..conftest import make_client


def test_health_is_ok_without_database(make_settings: Callable[..., Settings]) -> None:
    with make_client(create_app(make_settings())) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_is_503_when_database_unreachable(make_settings: Callable[..., Settings]) -> None:
    with make_client(create_app(make_settings())) as client:
        response = client.get("/api/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "database": "error"}


def test_docs_enabled_in_dev_only(make_settings: Callable[..., Settings]) -> None:
    with make_client(create_app(make_settings(env="dev"))) as client:
        assert client.get("/api/docs").status_code == 200
    with make_client(create_app(make_settings(env="prod"))) as client:
        assert client.get("/api/docs").status_code == 404
        assert client.get("/api/openapi.json").status_code == 404


def test_unknown_route_is_404_detail_shape(make_settings: Callable[..., Settings]) -> None:
    with make_client(create_app(make_settings())) as client:
        response = client.get("/api/nope")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_openapi_schema_has_stable_operation_ids() -> None:
    schema = openapi_schema()
    operation_ids = {
        operation["operationId"]
        for path in schema["paths"].values()
        for operation in path.values()
    }
    assert {"health", "ready"} <= operation_ids
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run --directory backend pytest tests/unit/test_health_api.py -q`
Expected: FAIL, `No module named 'ai_second_brain.interfaces'`.

- [ ] **Step 4: Implement `db.py`**

```python
"""PostgreSQL connection pool (psycopg 3, async)."""

import psycopg
from psycopg_pool import AsyncConnectionPool, PoolTimeout


def create_pool(database_url: str) -> AsyncConnectionPool:
    """Pool opened by the app lifespan. Connections are established in the background."""
    return AsyncConnectionPool(
        conninfo=database_url,
        min_size=1,
        max_size=5,
        open=False,
        timeout=3.0,
        kwargs={"connect_timeout": 3},
    )


async def ping(pool: AsyncConnectionPool, timeout: float = 2.0) -> bool:
    try:
        async with pool.connection(timeout=timeout) as conn:
            await conn.execute("SELECT 1")
    except (PoolTimeout, psycopg.Error, OSError):
        return False
    return True
```

- [ ] **Step 5: Implement `schemas.py`**

```python
"""Pydantic models that form the public API contract (and the generated TS client)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ReadyResponse(BaseModel):
    status: Literal["ready", "unavailable"]
    database: Literal["ok", "error"]


class ErrorResponse(BaseModel):
    detail: str


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=1024)


class MeResponse(BaseModel):
    authenticated: Literal[True]
    expires_at: datetime
```

- [ ] **Step 6: Implement `routes/health.py`**

```python
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ai_second_brain.db import ping
from ai_second_brain.interfaces.api.schemas import HealthResponse, ReadyResponse

router = APIRouter(tags=["health"])


@router.get("/health", operation_id="health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get(
    "/health/ready",
    operation_id="ready",
    response_model=ReadyResponse,
    responses={503: {"model": ReadyResponse}},
)
async def ready(request: Request):  # returns ReadyResponse or a 503 JSONResponse
    if await ping(request.app.state.pool):
        return ReadyResponse(status="ready", database="ok")
    return JSONResponse(status_code=503, content={"status": "unavailable", "database": "error"})
```

Create empty `__init__.py` files: `interfaces/__init__.py`, `interfaces/api/__init__.py` and `interfaces/api/routes/__init__.py`.

- [ ] **Step 7: Implement `app.py`**

```python
"""FastAPI application factory."""

import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import psycopg
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from psycopg_pool import PoolTimeout

from ai_second_brain.auth.throttle import LoginThrottle
from ai_second_brain.config import Settings, get_settings
from ai_second_brain.db import create_pool
from ai_second_brain.interfaces.api.routes import health

logger = logging.getLogger("ai_second_brain.api")

PLACEHOLDER_HASH = "$argon2id$v=19$m=65536,t=3,p=4$placeholder$placeholder"


def utc_now() -> datetime:
    return datetime.now(UTC)


async def _database_unavailable(request: Request, exc: Exception) -> JSONResponse:
    logger.warning("database unavailable: %s", type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "database_unavailable"})


async def _invalid_request(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": "invalid_request"})


async def _log_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "%s %s %s %.1fms", request.method, request.url.path, response.status_code, elapsed_ms
    )
    return response


def create_app(
    settings: Settings | None = None,
    *,
    clock: Callable[[], datetime] = utc_now,
    throttle_clock: Callable[[], float] = time.monotonic,
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        pool = create_pool(settings.database_url)
        await pool.open(wait=False)
        app.state.pool = pool
        try:
            yield
        finally:
            await pool.close()

    docs_enabled = settings.env == "dev"
    app = FastAPI(
        title="Second Brain API",
        version="0.2.0",
        lifespan=lifespan,
        docs_url="/api/docs" if docs_enabled else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if docs_enabled else None,
    )
    app.state.settings = settings
    app.state.clock = clock
    app.state.throttle = LoginThrottle(clock=throttle_clock)

    app.add_exception_handler(PoolTimeout, _database_unavailable)
    app.add_exception_handler(psycopg.OperationalError, _database_unavailable)
    app.add_exception_handler(RequestValidationError, _invalid_request)
    app.middleware("http")(_log_requests)

    app.include_router(health.router, prefix="/api")
    return app


def openapi_schema() -> dict[str, Any]:
    """OpenAPI document without needing a real .env or database."""
    settings = Settings(  # pyright: ignore[reportCallIssue]
        _env_file=None,
        DATABASE_URL="postgres://unused@127.0.0.1:1/unused",
        owner_password_hash=PLACEHOLDER_HASH,
        env="dev",
    )
    return create_app(settings).openapi()
```

- [ ] **Step 8: Run to verify they pass**

Run: `uv run --directory backend pytest tests/unit/test_health_api.py -q`
Expected: `5 passed`. The ready test takes about 2 s, because it waits for the pool timeout.

- [ ] **Step 9: Static checks and commit**

Run: `just backend::fmt`, then `just backend::check`
Expected: clean.

```bash
git add -A
git commit -m "feat(api): add app factory and health endpoints" -m "Add the async psycopg pool and /api/health and /api/health/ready."
```

---

### Task 6: Sessions, CSRF guard and auth endpoints

**Files:**
- Create: `backend/src/ai_second_brain/auth/sessions.py`, `backend/src/ai_second_brain/interfaces/api/deps.py`, `backend/src/ai_second_brain/interfaces/api/routes/auth.py`, `backend/tests/unit/test_csrf.py`, `backend/tests/integration/__init__.py`, `backend/tests/integration/test_auth_api.py`
- Modify: `backend/src/ai_second_brain/interfaces/api/app.py` (sessions in lifespan, include the auth router)

**Interfaces:**
- Consumes: `create_pool`, `LoginThrottle`, `verify_password`, `Settings`, `utc_now` (Tasks 3–5).
- Produces:
  - `sessions.Session(id: bytes, created_at: datetime, last_seen_at: datetime, expires_at: datetime)` and `sessions.token_id(token: str) -> bytes`.
  - `sessions.SessionStore(pool, ttl: timedelta, clock: Callable[[], datetime])` with `create(user_agent: str | None) -> str`, `get(token: str) -> Session | None`, `touch(session) -> Session`, `revoke(token: str) -> None` and `purge_expired() -> int` (all async).
  - `deps.SESSION_COOKIE = "sb_session"` and `deps.is_same_origin(method, sec_fetch_site, origin, allowed) -> bool`.
  - Routes `POST /api/auth/login`, `POST /api/auth/logout` and `GET /api/auth/me`.

- [ ] **Step 1: Write the failing CSRF unit test `backend/tests/unit/test_csrf.py`**

```python
import pytest

from ai_second_brain.interfaces.api.deps import is_same_origin

ALLOWED = frozenset({"http://localhost:5173"})


@pytest.mark.parametrize(
    ("method", "fetch_site", "origin", "expected"),
    [
        ("GET", None, None, True),  # safe methods are never checked
        ("HEAD", "cross-site", "http://evil.example", True),
        ("POST", "same-origin", None, True),
        ("POST", None, "http://localhost:5173", True),
        ("POST", None, "http://localhost:5173/", True),  # trailing slash tolerated
        ("POST", "cross-site", "http://localhost:5173", True),  # allowed origin wins
        ("POST", "cross-site", "http://evil.example", False),
        ("POST", None, "http://evil.example", False),
        ("POST", None, None, False),  # non-browser clients are rejected
        ("DELETE", "same-site", None, False),
        ("PATCH", None, "null", False),
    ],
)
def test_is_same_origin(
    method: str, fetch_site: str | None, origin: str | None, expected: bool
) -> None:
    assert is_same_origin(method, fetch_site, origin, ALLOWED) is expected
```

(You run it together with the integration tests in Step 3.)

- [ ] **Step 2: Write the failing integration tests `backend/tests/integration/test_auth_api.py`**

```python
import logging
import os
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient

from ai_second_brain.auth.sessions import token_id
from ai_second_brain.config import Settings
from ai_second_brain.interfaces.api.app import create_app

from ..conftest import SAME_ORIGIN, TEST_PASSWORD, make_client

pytestmark = pytest.mark.integration


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def db_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail("TEST_DATABASE_URL is not set. Run tests with `just test` from the repo root.")
    return url


@pytest.fixture
def db(db_url: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("TRUNCATE auth_sessions")
        yield conn


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def settings(make_settings: Callable[..., Settings], db_url: str) -> Settings:
    return make_settings(DATABASE_URL=db_url)


@pytest.fixture
def client(
    settings: Settings, clock: FakeClock, db: psycopg.Connection
) -> Iterator[TestClient]:
    with make_client(create_app(settings, clock=clock)) as test_client:
        yield test_client


def login(client: TestClient, password: str = TEST_PASSWORD, **headers: str):
    return client.post(
        "/api/auth/login", json={"password": password}, headers=headers or SAME_ORIGIN
    )


def session_count(db: psycopg.Connection) -> int:
    row = db.execute("SELECT count(*) FROM auth_sessions").fetchone()
    assert row is not None
    return row[0]


def test_login_sets_cookie_and_me_works(client: TestClient, db: psycopg.Connection) -> None:
    response = login(client)
    assert response.status_code == 204
    cookie_header = response.headers["set-cookie"].lower()
    for attribute in ("httponly", "samesite=strict", "path=/api", "max-age=1209600"):
        assert attribute in cookie_header
    assert "secure" not in cookie_header
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["authenticated"] is True
    assert session_count(db) == 1


def test_only_token_hash_is_stored(client: TestClient, db: psycopg.Connection) -> None:
    login(client)
    token = client.cookies["sb_session"]
    row = db.execute("SELECT id FROM auth_sessions").fetchone()
    assert row is not None
    assert bytes(row[0]) == token_id(token)
    assert token.encode() not in bytes(row[0])


def test_wrong_password_is_401_and_creates_no_session(
    client: TestClient, db: psycopg.Connection
) -> None:
    response = login(client, "wrong")
    assert response.status_code == 401
    assert response.json() == {"detail": "invalid_credentials"}
    assert session_count(db) == 0


def test_sixth_rapid_failure_is_throttled(client: TestClient) -> None:
    for _ in range(5):
        assert login(client, "wrong").status_code == 401
    response = login(client, "wrong")
    assert response.status_code == 429
    assert response.json() == {"detail": "too_many_attempts"}
    assert 1 <= int(response.headers["retry-after"]) <= 60
    assert login(client).status_code == 429  # even the right password waits


def test_cross_origin_and_headerless_login_rejected(client: TestClient) -> None:
    assert login(client, **{"Origin": "http://evil.example"}).status_code == 403
    response = client.post("/api/auth/login", json={"password": TEST_PASSWORD})
    assert response.status_code == 403
    assert response.json() == {"detail": "cross_origin"}


@pytest.mark.parametrize(
    "body",
    [
        {"password": "x" * 1_000_000},
        {"password": ""},
        {},
        {"password": TEST_PASSWORD, "extra": 1},
    ],
)
def test_invalid_login_bodies_are_422_and_not_counted(client: TestClient, body: object) -> None:
    for _ in range(6):
        response = client.post("/api/auth/login", json=body, headers=SAME_ORIGIN)
        assert response.status_code == 422
        assert response.json() == {"detail": "invalid_request"}
    assert login(client).status_code == 204  # throttle untouched


def test_non_json_login_body_is_422(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        content=b"password=hunter2",
        headers={**SAME_ORIGIN, "Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("cookie", ["", "not-a-token", "x" * 5000, "%%%;;;"])
def test_garbage_cookies_are_401_not_500(client: TestClient, cookie: str) -> None:
    response = client.get("/api/auth/me", headers={"Cookie": f"sb_session={cookie}"})
    assert response.status_code == 401
    assert response.json() == {"detail": "not_authenticated"}


def test_logout_revokes_and_is_idempotent(client: TestClient, db: psycopg.Connection) -> None:
    login(client)
    token = client.cookies["sb_session"]
    response = client.post("/api/auth/logout", headers=SAME_ORIGIN)
    assert response.status_code == 204
    assert session_count(db) == 0
    client.cookies.clear()
    assert client.get("/api/auth/me").status_code == 401
    replay = client.get("/api/auth/me", headers={"Cookie": f"sb_session={token}"})
    assert replay.status_code == 401
    assert client.post("/api/auth/logout", headers=SAME_ORIGIN).status_code == 204


def test_expired_session_rejected_and_purged_on_startup(
    settings: Settings, clock: FakeClock, client: TestClient, db: psycopg.Connection
) -> None:
    login(client)
    clock.now += timedelta(days=15)
    assert client.get("/api/auth/me").status_code == 401
    with make_client(create_app(settings, clock=clock)):
        pass
    assert session_count(db) == 0


def test_touch_slides_expiry_at_most_every_five_minutes(
    client: TestClient, clock: FakeClock, db: psycopg.Connection
) -> None:
    login(client)
    start = clock.now

    def last_seen() -> datetime:
        row = db.execute("SELECT last_seen_at FROM auth_sessions").fetchone()
        assert row is not None
        return row[0]

    clock.now = start + timedelta(minutes=1)
    assert client.get("/api/auth/me").status_code == 200
    assert last_seen() == start
    clock.now = start + timedelta(minutes=6)
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert last_seen() == clock.now
    assert datetime.fromisoformat(me.json()["expires_at"]) == clock.now + timedelta(days=14)
    assert "max-age=1209600" in me.headers["set-cookie"].lower()


def test_logs_never_contain_password_or_token(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    login(client)
    token = client.cookies["sb_session"]
    client.get("/api/auth/me")
    assert TEST_PASSWORD not in caplog.text
    assert token not in caplog.text
    assert "POST /api/auth/login 204" in caplog.text


def test_login_and_me_are_503_when_database_down(
    make_settings: Callable[..., Settings],
) -> None:
    with make_client(create_app(make_settings())) as dead:  # default settings point at port 1
        response = dead.post(
            "/api/auth/login", json={"password": TEST_PASSWORD}, headers=SAME_ORIGIN
        )
        assert response.status_code == 503
        assert response.json() == {"detail": "database_unavailable"}
        me = dead.get("/api/auth/me", headers={"Cookie": "sb_session=some-token"})
        assert me.status_code == 503
```

- [ ] **Step 3: Run to verify they fail**

Run (Docker up; `just db::test-prepare` done in Task 2): `just backend::test tests/unit/test_csrf.py tests/integration -q`
Expected: FAIL. `test_csrf.py` can't import `ai_second_brain.interfaces.api.deps`, and the integration tests can't import `ai_second_brain.auth.sessions`.

- [ ] **Step 4: Implement `auth/sessions.py`**

```python
"""Server-side sessions. Only sha256(token) is stored; the raw token lives in the cookie."""

import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from psycopg_pool import AsyncConnectionPool

TOUCH_INTERVAL = timedelta(minutes=5)
MAX_TOKEN_LENGTH = 256


@dataclass(frozen=True, slots=True)
class Session:
    id: bytes
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime


def token_id(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


class SessionStore:
    def __init__(
        self, pool: AsyncConnectionPool, ttl: timedelta, clock: Callable[[], datetime]
    ) -> None:
        self._pool = pool
        self._ttl = ttl
        self._clock = clock

    async def create(self, user_agent: str | None) -> str:
        token = secrets.token_urlsafe(32)
        now = self._clock()
        agent = (user_agent or "")[:512] or None
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO auth_sessions (id, created_at, last_seen_at, expires_at, user_agent)"
                " VALUES (%s, %s, %s, %s, %s)",
                (token_id(token), now, now, now + self._ttl, agent),
            )
        return token

    async def get(self, token: str) -> Session | None:
        if not token or len(token) > MAX_TOKEN_LENGTH:
            return None
        async with self._pool.connection() as conn:
            cursor = await conn.execute(
                "SELECT id, created_at, last_seen_at, expires_at FROM auth_sessions"
                " WHERE id = %s AND expires_at > %s",
                (token_id(token), self._clock()),
            )
            row = await cursor.fetchone()
        return Session(*row) if row else None

    async def touch(self, session: Session) -> Session:
        """Slide the expiry forward, writing at most once per TOUCH_INTERVAL."""
        now = self._clock()
        if now - session.last_seen_at < TOUCH_INTERVAL:
            return session
        expires_at = now + self._ttl
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE auth_sessions SET last_seen_at = %s, expires_at = %s WHERE id = %s",
                (now, expires_at, session.id),
            )
        return replace(session, last_seen_at=now, expires_at=expires_at)

    async def revoke(self, token: str) -> None:
        if not token or len(token) > MAX_TOKEN_LENGTH:
            return
        async with self._pool.connection() as conn:
            await conn.execute("DELETE FROM auth_sessions WHERE id = %s", (token_id(token),))

    async def purge_expired(self) -> int:
        async with self._pool.connection(timeout=2.0) as conn:
            cursor = await conn.execute(
                "DELETE FROM auth_sessions WHERE expires_at <= %s", (self._clock(),)
            )
            return cursor.rowcount
```

- [ ] **Step 5: Implement `interfaces/api/deps.py`**

```python
"""Request dependencies: CSRF origin check, session resolution, cookie helpers."""

from fastapi import Depends, HTTPException, Request, Response, status

from ai_second_brain.auth.sessions import Session, SessionStore
from ai_second_brain.config import Settings

SESSION_COOKIE = "sb_session"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def is_same_origin(
    method: str, sec_fetch_site: str | None, origin: str | None, allowed: frozenset[str]
) -> bool:
    if method.upper() not in UNSAFE_METHODS:
        return True
    if sec_fetch_site == "same-origin":
        return True
    return origin is not None and origin.rstrip("/") in allowed


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_store(request: Request) -> SessionStore:
    return request.app.state.sessions


async def require_same_origin(request: Request) -> None:
    allowed = get_settings(request).allowed_origin_set
    if not is_same_origin(
        request.method,
        request.headers.get("sec-fetch-site"),
        request.headers.get("origin"),
        allowed,
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="cross_origin")


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_days * 24 * 3600,
        path="/api",
        httponly=True,
        samesite="strict",
        secure=settings.cookie_secure,
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        SESSION_COOKIE, path="/api", httponly=True, samesite="strict", secure=settings.cookie_secure
    )


async def optional_session(request: Request, response: Response) -> Session | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    store = get_store(request)
    session = await store.get(token)
    if session is None:
        return None
    touched = await store.touch(session)
    if touched is not session:
        set_session_cookie(response, token, get_settings(request))
    return touched


async def require_session(session: Session | None = Depends(optional_session)) -> Session:  # noqa: B008
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="not_authenticated")
    return session
```

- [ ] **Step 6: Implement `routes/auth.py`**

```python
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from starlette.concurrency import run_in_threadpool

from ai_second_brain.auth.passwords import verify_password
from ai_second_brain.auth.sessions import Session
from ai_second_brain.interfaces.api.deps import (
    SESSION_COOKIE,
    clear_session_cookie,
    get_settings,
    get_store,
    require_same_origin,
    require_session,
    set_session_cookie,
)
from ai_second_brain.interfaces.api.schemas import ErrorResponse, LoginRequest, MeResponse

router = APIRouter(tags=["auth"])

ERRORS = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}


@router.post(
    "/login",
    operation_id="login",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    dependencies=[Depends(require_same_origin)],
    responses={**ERRORS, 429: {"model": ErrorResponse}},
)
async def login(body: LoginRequest, request: Request, response: Response) -> None:
    settings = get_settings(request)
    throttle = request.app.state.throttle
    wait = throttle.retry_after()
    if wait is not None:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too_many_attempts",
            headers={"Retry-After": str(wait)},
        )
    # argon2 is CPU-heavy; keep it off the event loop.
    if not await run_in_threadpool(verify_password, settings.owner_password_hash, body.password):
        throttle.record_failure()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials")
    throttle.record_success()
    token = await get_store(request).create(request.headers.get("user-agent"))
    set_session_cookie(response, token, settings)


@router.post(
    "/logout",
    operation_id="logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    dependencies=[Depends(require_same_origin)],
    responses=ERRORS,
)
async def logout(request: Request, response: Response) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await get_store(request).revoke(token)
    clear_session_cookie(response, get_settings(request))


@router.get("/me", operation_id="me", response_model=MeResponse, responses=ERRORS)
async def me(session: Session = Depends(require_session)) -> MeResponse:  # noqa: B008
    return MeResponse(authenticated=True, expires_at=session.expires_at)
```

- [ ] **Step 7: Wire sessions into `app.py`**

Change `from datetime import UTC, datetime` to `from datetime import UTC, datetime, timedelta`, and add:

```python
from ai_second_brain.auth.sessions import SessionStore
from ai_second_brain.interfaces.api.routes import auth  # next to the existing `health` import
```

Replace the `lifespan` body with:

```python
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        pool = create_pool(settings.database_url)
        await pool.open(wait=False)
        app.state.pool = pool
        app.state.sessions = SessionStore(pool, timedelta(days=settings.session_ttl_days), clock)
        try:
            await app.state.sessions.purge_expired()
        except (PoolTimeout, psycopg.Error, OSError):
            logger.warning("session purge skipped: database unavailable")
        try:
            yield
        finally:
            await pool.close()
```

After `app.include_router(health.router, prefix="/api")`, add:

```python
    app.include_router(auth.router, prefix="/api/auth")
```

Extend `test_openapi_schema_has_stable_operation_ids` in `tests/unit/test_health_api.py`: change the assertion to `assert {"health", "ready", "login", "logout", "me"} <= operation_ids`.

- [ ] **Step 8: Run to verify they pass**

Run: `just backend::test tests/unit/test_csrf.py tests/integration -q`
Expected: all pass. `test_login_and_me_are_503_when_database_down` takes about 8 s, because it waits for pool timeouts against a closed port.

- [ ] **Step 9: Full backend run, then commit**

Run: `just backend::test`, then `just backend::check`
Expected: all green.

```bash
git add -A
git commit -m "feat(auth): add sessions and login/logout/me API" -m "Store only sha256 token ids server-side, reject cross-origin writes
and throttle failed logins."
```

---

### Task 7: Admin CLI (serve, openapi, hash-password)

**Files:**
- Create: `backend/src/ai_second_brain/interfaces/cli/__init__.py`, `backend/src/ai_second_brain/interfaces/cli/main.py`, `backend/tests/unit/test_cli.py`
- Modify: `backend/justfile` (add `serve`); root `justfile` (add `hash-password`)

**Interfaces:**
- Consumes: `openapi_schema()`, `get_settings()`, `hash_password`, `HASH_HINT`.
- Produces: the console script `ai-second-brain` with `serve [--reload] [--port N]`, `openapi [--output PATH]` and `hash-password`. Output of `hash-password` is exactly one line: `SB_OWNER_PASSWORD_HASH='<hash>'`.

- [ ] **Step 1: Write the failing tests `backend/tests/unit/test_cli.py`**

```python
import json
from pathlib import Path

from typer.testing import CliRunner

from ai_second_brain.auth.passwords import verify_password
from ai_second_brain.interfaces.cli.main import app

runner = CliRunner()


def test_openapi_writes_file_with_lf_and_sorted_keys(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "openapi.json"
    result = runner.invoke(app, ["openapi", "--output", str(target)])
    assert result.exit_code == 0, result.output
    raw = target.read_bytes()
    assert b"\r\n" not in raw
    schema = json.loads(raw)
    operation_ids = {op["operationId"] for p in schema["paths"].values() for op in p.values()}
    assert operation_ids >= {"health", "ready", "login", "logout", "me"}


def test_openapi_is_deterministic(tmp_path: Path) -> None:
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    runner.invoke(app, ["openapi", "--output", str(first)])
    runner.invoke(app, ["openapi", "--output", str(second)])
    assert first.read_bytes() == second.read_bytes()


def test_openapi_to_stdout() -> None:
    result = runner.invoke(app, ["openapi"])
    assert result.exit_code == 0
    assert json.loads(result.output)["info"]["title"] == "Second Brain API"


def test_hash_password_prints_single_quoted_env_line() -> None:
    password = "zażółć gęślą jaźń 🔑 "
    result = runner.invoke(app, ["hash-password"], input=f"{password}\n{password}\n")
    assert result.exit_code == 0, result.output
    line = result.output.strip().splitlines()[-1]
    assert line.startswith("SB_OWNER_PASSWORD_HASH='$argon2id$")
    assert line.endswith("'")
    assert verify_password(line.split("=", 1)[1].strip("'"), password)


def test_hash_password_rejects_mismatch() -> None:
    result = runner.invoke(app, ["hash-password"], input="one\ntwo\none\none\n")
    assert "Error: The two entered values do not match." in result.output
```

Run: `uv run --directory backend pytest tests/unit/test_cli.py -q`
Expected: FAIL (import error).

- [ ] **Step 2: Implement `interfaces/cli/main.py`** (and an empty `interfaces/cli/__init__.py`)

```python
"""Admin CLI: `ai-second-brain serve | openapi | hash-password`."""

import json
from pathlib import Path
from typing import Annotated

import typer
import uvicorn
from pydantic import ValidationError

from ai_second_brain.auth.passwords import hash_password
from ai_second_brain.config import get_settings
from ai_second_brain.interfaces.api.app import openapi_schema

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Second Brain admin CLI.")

SRC_DIR = Path(__file__).resolve().parents[2]


@app.command()
def serve(
    reload: Annotated[bool, typer.Option(help="Restart on code changes (dev).")] = False,
    port: Annotated[int | None, typer.Option(help="Port (default: SB_API_PORT).")] = None,
) -> None:
    """Run the API on 127.0.0.1."""
    try:
        settings = get_settings()
    except ValidationError as error:
        typer.echo(f"Configuration error:\n{error}", err=True)
        raise typer.Exit(code=1) from error
    uvicorn.run(
        "ai_second_brain.interfaces.api.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=port or settings.api_port,
        reload=reload,
        reload_dirs=[str(SRC_DIR)] if reload else None,
        loop="ai_second_brain.runtime:new_event_loop",
        access_log=False,
    )


@app.command()
def openapi(
    output: Annotated[
        Path | None, typer.Option(help="Write to this file instead of stdout.")
    ] = None,
) -> None:
    """Print or write the OpenAPI schema (deterministic: sorted keys, LF endings)."""
    text = json.dumps(openapi_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if output is None:
        typer.echo(text, nl=False)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8", newline="\n")


@app.command("hash-password")
def hash_password_command() -> None:
    """Hash the owner password and print the .env line (nothing is written to disk)."""
    password: str = typer.prompt("Password", hide_input=True, confirmation_prompt=True)
    typer.echo(f"SB_OWNER_PASSWORD_HASH='{hash_password(password)}'")
```

- [ ] **Step 3: Run the tests**

Run: `uv run --directory backend pytest tests/unit/test_cli.py -q`
Expected: all pass. If click's mismatch message text differs in the installed version, run the test and copy the actual `Error:` line into the assertion. The behavior (re-prompt on mismatch) is what matters.

- [ ] **Step 4: Add the recipes**

`backend/justfile`:

```just
# Run the API (pass --reload for development)
serve *args:
    uv run ai-second-brain serve {{ args }}
```

Root `justfile`:

```just
# Hash the owner password; paste the printed line into .env
hash-password:
    uv run --directory backend ai-second-brain hash-password
```

- [ ] **Step 5: Manual smoke test (Windows event loop)**

Run: `just hash-password`, type any password twice, and paste the line into `.env`, replacing the empty `SB_OWNER_PASSWORD_HASH=''`.
Run: `just backend::serve --reload`, then open `http://127.0.0.1:8000/api/health/ready` in a browser.
Expected: `{"database":"ok","status":"ready"}` with Postgres up. The server log shows no `ProactorEventLoop` error from psycopg. Stop it with Ctrl+C.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(cli): add serve, openapi, hash-password"
```

---

### Task 8: Web scaffold, design tokens and token checks

**Files:**
- Create: `web/package.json`, `web/tsconfig.json`, `web/vite.config.ts`, `web/biome.json`, `web/index.html`, `web/justfile`, `web/src/index.css`, `web/src/design-system/tokens.css`, `web/src/design-system/cn.ts`, `web/src/test/setup.ts`, `web/scripts/check-contrast.ts`, `web/scripts/check-contrast.test.ts`, `web/scripts/check-colors.ts`, `web/scripts/check-colors.test.ts`
- Modify: root `justfile` (`mod web`)

**Interfaces:**
- Produces:
  - CSS custom properties `--sb-*` (semantic: `bg`, `surface`, `surface-raised`, `text`, `text-muted`, `border`, `border-input`, `focus-ring`, `accent`, `accent-fg`; roles `green|violet|amber|red|cyan|blue|neutral` × `fg|bg|border`; domain aliases `tier-*`, `ingest-*`, `salience-*`, `node-*`, `link-*`, `danger|success|warning`).
  - Tailwind color utilities `bg`, `surface`, `surface-raised`, `fg`, `fg-muted`, `border`, `border-input`, `ring`, `accent`, `accent-fg`, `danger-fg`, `danger-bg`, `danger-border`.
  - `cn(...inputs: ClassValue[]): string`.
  - `checkTokens(css: string): { failures: Failure[]; checked: number }` and `findViolations(source: string): Violation[]`.
  - Recipes `web::check`, `web::test`, `web::dev`, `web::build`, `web::fmt`.

- [ ] **Step 1: Create `web/package.json` and install dependencies**

```json
{
  "name": "@ai-second-brain/web",
  "private": true,
  "type": "module",
  "engines": {
    "node": ">=24"
  }
}
```

From the repo root:

```bash
pnpm --dir web add react react-dom @tanstack/react-router @tanstack/react-query openapi-fetch class-variance-authority clsx tailwind-merge @radix-ui/react-slot @radix-ui/react-label lucide-react @fontsource-variable/inter @fontsource-variable/jetbrains-mono
pnpm --dir web add -D typescript@~5.9.3 vite @vitejs/plugin-react @tanstack/router-plugin @tanstack/router-cli tailwindcss @tailwindcss/vite @biomejs/biome vitest jsdom @testing-library/react @testing-library/user-event @testing-library/jest-dom @playwright/test openapi-typescript culori @types/culori tsx @types/react @types/react-dom @types/node
```

Expected: success. Versions verified at planning time: react 19.3, vite 8.3, vitest 5.0, tailwindcss 4.3, @biomejs/biome 2.5, @tanstack/react-router 1.170, openapi-typescript 7.13, culori 4.0. If pnpm reports `ERR_PNPM_IGNORED_BUILDS`, apply the Task 1 Step 7 rule.

- [ ] **Step 2: Write `web/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2023",
    "lib": ["ES2023", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "exactOptionalPropertyTypes": true,
    "noImplicitOverride": true,
    "noFallthroughCasesInSwitch": true,
    "verbatimModuleSyntax": true,
    "isolatedModules": true,
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "skipLibCheck": true,
    "noEmit": true,
    "types": ["vite/client", "node"],
    "paths": { "@/*": ["./src/*"] }
  },
  "include": ["src", "scripts", "tests", "vite.config.ts", "playwright.config.ts"]
}
```

- [ ] **Step 3: Write `web/vite.config.ts`**

```ts
import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import { tanstackRouter } from "@tanstack/router-plugin/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const apiPort = process.env.SB_API_PORT ?? "8000";
const webPort = Number(process.env.SB_WEB_PORT ?? "5173");

export default defineConfig({
  plugins: [tanstackRouter({ target: "react", autoCodeSplitting: true }), react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    port: webPort,
    strictPort: true,
    proxy: { "/api": { target: `http://127.0.0.1:${apiPort}`, changeOrigin: false } },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}", "scripts/**/*.test.ts"],
    css: false,
  },
});
```

- [ ] **Step 4: Write `web/biome.json`, `web/index.html`, `web/src/test/setup.ts` and `web/src/design-system/cn.ts`**

`web/biome.json`:

```json
{
  "$schema": "./node_modules/@biomejs/biome/configuration_schema.json",
  "files": {
    "includes": [
      "**",
      "!src/routeTree.gen.ts",
      "!src/api/schema.d.ts",
      "!src/api/openapi.json",
      "!**/dist",
      "!**/test-results",
      "!**/playwright-report"
    ]
  },
  "formatter": { "indentStyle": "space", "indentWidth": 2, "lineWidth": 100 },
  "css": { "parser": { "tailwindDirectives": true } },
  "linter": { "enabled": true, "rules": { "recommended": true } },
  "assist": { "actions": { "source": { "organizeImports": "on" } } }
}
```

`web/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <meta name="color-scheme" content="light dark" />
    <title>Second Brain</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`web/src/test/setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(() => {
  cleanup();
  document.documentElement.removeAttribute("data-theme");
  window.localStorage.clear();
});

if (typeof window.matchMedia !== "function") {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
}
```

`web/src/design-system/cn.ts`:

```ts
import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
```

- [ ] **Step 5: Write `web/src/design-system/tokens.css`**

Every value below was verified during planning. Each text pair is at least 4.5:1 and each border/focus pair at least 3:1 in both themes, with all colors inside sRGB.

```css
/* Design tokens: palette/roles → semantic → domain.
   Components use Tailwind utilities mapped in @theme, or domain variables. Never literals. */

@custom-variant dark (&:where([data-theme="dark"], [data-theme="dark"] *));

:root {
  color-scheme: light;

  --sb-bg: oklch(0.99 0 0);
  --sb-surface: oklch(0.97 0.004 260);
  --sb-surface-raised: oklch(1 0 0);
  --sb-text: oklch(0.22 0.012 260);
  --sb-text-muted: oklch(0.46 0.012 260);
  --sb-border: oklch(0.9 0.006 260);
  --sb-border-input: oklch(0.6 0.012 260);
  --sb-focus-ring: oklch(0.52 0.14 260);
  --sb-accent: oklch(0.48 0.14 260);
  --sb-accent-fg: oklch(0.99 0 0);

  --sb-green-fg: oklch(0.44 0.09 145);
  --sb-green-bg: oklch(0.955 0.018 145);
  --sb-green-border: oklch(0.6 0.08 145);
  --sb-violet-fg: oklch(0.44 0.09 295);
  --sb-violet-bg: oklch(0.955 0.018 295);
  --sb-violet-border: oklch(0.6 0.08 295);
  --sb-amber-fg: oklch(0.44 0.09 75);
  --sb-amber-bg: oklch(0.955 0.018 75);
  --sb-amber-border: oklch(0.6 0.08 75);
  --sb-red-fg: oklch(0.44 0.09 25);
  --sb-red-bg: oklch(0.955 0.018 25);
  --sb-red-border: oklch(0.6 0.08 25);
  --sb-cyan-fg: oklch(0.44 0.07 215);
  --sb-cyan-bg: oklch(0.955 0.018 215);
  --sb-cyan-border: oklch(0.6 0.08 215);
  --sb-blue-fg: oklch(0.44 0.09 260);
  --sb-blue-bg: oklch(0.955 0.018 260);
  --sb-blue-border: oklch(0.6 0.08 260);
  --sb-neutral-fg: oklch(0.44 0.012 260);
  --sb-neutral-bg: oklch(0.95 0.004 260);
  --sb-neutral-border: oklch(0.62 0.012 260);

  --sb-danger-fg: var(--sb-red-fg);
  --sb-danger-bg: var(--sb-red-bg);
  --sb-danger-border: var(--sb-red-border);
  --sb-success-fg: var(--sb-green-fg);
  --sb-success-bg: var(--sb-green-bg);
  --sb-success-border: var(--sb-green-border);
  --sb-warning-fg: var(--sb-amber-fg);
  --sb-warning-bg: var(--sb-amber-bg);
  --sb-warning-border: var(--sb-amber-border);

  --sb-tier-private-fg: var(--sb-green-fg);
  --sb-tier-private-bg: var(--sb-green-bg);
  --sb-tier-private-border: var(--sb-green-border);
  --sb-tier-cloud-fg: var(--sb-violet-fg);
  --sb-tier-cloud-bg: var(--sb-violet-bg);
  --sb-tier-cloud-border: var(--sb-violet-border);
  --sb-tier-withheld-fg: var(--sb-amber-fg);
  --sb-tier-withheld-bg: var(--sb-amber-bg);
  --sb-tier-withheld-border: var(--sb-amber-border);

  --sb-ingest-pending-fg: var(--sb-neutral-fg);
  --sb-ingest-pending-bg: var(--sb-neutral-bg);
  --sb-ingest-pending-border: var(--sb-neutral-border);
  --sb-ingest-searchable-fg: var(--sb-green-fg);
  --sb-ingest-searchable-bg: var(--sb-green-bg);
  --sb-ingest-searchable-border: var(--sb-green-border);
  --sb-ingest-failed-fg: var(--sb-red-fg);
  --sb-ingest-failed-bg: var(--sb-red-bg);
  --sb-ingest-failed-border: var(--sb-red-border);

  --sb-salience-dormant-fg: var(--sb-neutral-fg);
  --sb-salience-dormant-bg: var(--sb-neutral-bg);
  --sb-salience-dormant-border: var(--sb-neutral-border);
  --sb-salience-superseded-fg: var(--sb-amber-fg);
  --sb-salience-superseded-bg: var(--sb-amber-bg);
  --sb-salience-superseded-border: var(--sb-amber-border);
  --sb-salience-archived-fg: var(--sb-neutral-fg);
  --sb-salience-archived-bg: var(--sb-neutral-bg);
  --sb-salience-archived-border: var(--sb-neutral-border);
  --sb-salience-pinned-fg: var(--sb-amber-fg);
  --sb-salience-pinned-bg: var(--sb-amber-bg);
  --sb-salience-pinned-border: var(--sb-amber-border);
  --sb-salience-from-earlier-fg: var(--sb-blue-fg);
  --sb-salience-from-earlier-bg: var(--sb-blue-bg);
  --sb-salience-from-earlier-border: var(--sb-blue-border);

  --sb-node-online-fg: var(--sb-green-fg);
  --sb-node-online-bg: var(--sb-green-bg);
  --sb-node-online-border: var(--sb-green-border);
  --sb-node-waking-fg: var(--sb-cyan-fg);
  --sb-node-waking-bg: var(--sb-cyan-bg);
  --sb-node-waking-border: var(--sb-cyan-border);
  --sb-node-unreachable-fg: var(--sb-red-fg);
  --sb-node-unreachable-bg: var(--sb-red-bg);
  --sb-node-unreachable-border: var(--sb-red-border);
  --sb-node-unknown-fg: var(--sb-neutral-fg);
  --sb-node-unknown-bg: var(--sb-neutral-bg);
  --sb-node-unknown-border: var(--sb-neutral-border);

  --sb-link-proposed-fg: var(--sb-amber-fg);
  --sb-link-proposed-bg: var(--sb-amber-bg);
  --sb-link-proposed-border: var(--sb-amber-border);
  --sb-link-accepted-fg: var(--sb-green-fg);
  --sb-link-accepted-bg: var(--sb-green-bg);
  --sb-link-accepted-border: var(--sb-green-border);
  --sb-link-rejected-fg: var(--sb-neutral-fg);
  --sb-link-rejected-bg: var(--sb-neutral-bg);
  --sb-link-rejected-border: var(--sb-neutral-border);
}

[data-theme="dark"] {
  color-scheme: dark;

  --sb-bg: oklch(0.17 0.01 260);
  --sb-surface: oklch(0.21 0.012 260);
  --sb-surface-raised: oklch(0.25 0.012 260);
  --sb-text: oklch(0.95 0.005 260);
  --sb-text-muted: oklch(0.74 0.01 260);
  --sb-border: oklch(0.32 0.012 260);
  --sb-border-input: oklch(0.52 0.012 260);
  --sb-focus-ring: oklch(0.72 0.12 260);
  --sb-accent: oklch(0.74 0.11 260);
  --sb-accent-fg: oklch(0.17 0.01 260);

  --sb-green-fg: oklch(0.86 0.07 145);
  --sb-green-bg: oklch(0.28 0.04 145);
  --sb-green-border: oklch(0.58 0.08 145);
  --sb-violet-fg: oklch(0.86 0.07 295);
  --sb-violet-bg: oklch(0.28 0.04 295);
  --sb-violet-border: oklch(0.58 0.08 295);
  --sb-amber-fg: oklch(0.86 0.07 75);
  --sb-amber-bg: oklch(0.28 0.04 75);
  --sb-amber-border: oklch(0.58 0.08 75);
  --sb-red-fg: oklch(0.86 0.07 25);
  --sb-red-bg: oklch(0.28 0.04 25);
  --sb-red-border: oklch(0.58 0.08 25);
  --sb-cyan-fg: oklch(0.86 0.07 215);
  --sb-cyan-bg: oklch(0.28 0.04 215);
  --sb-cyan-border: oklch(0.58 0.08 215);
  --sb-blue-fg: oklch(0.86 0.05 260);
  --sb-blue-bg: oklch(0.28 0.04 260);
  --sb-blue-border: oklch(0.58 0.08 260);
  --sb-neutral-fg: oklch(0.8 0.01 260);
  --sb-neutral-bg: oklch(0.27 0.01 260);
  --sb-neutral-border: oklch(0.55 0.012 260);
}

@theme {
  --color-*: initial;
}

@theme inline {
  --color-bg: var(--sb-bg);
  --color-surface: var(--sb-surface);
  --color-surface-raised: var(--sb-surface-raised);
  --color-fg: var(--sb-text);
  --color-fg-muted: var(--sb-text-muted);
  --color-border: var(--sb-border);
  --color-border-input: var(--sb-border-input);
  --color-ring: var(--sb-focus-ring);
  --color-accent: var(--sb-accent);
  --color-accent-fg: var(--sb-accent-fg);
  --color-danger-fg: var(--sb-danger-fg);
  --color-danger-bg: var(--sb-danger-bg);
  --color-danger-border: var(--sb-danger-border);

  --font-sans: "Inter Variable", ui-sans-serif, system-ui, sans-serif;
  --font-mono: "JetBrains Mono Variable", ui-monospace, monospace;

  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
}
```

`web/src/index.css`:

```css
@import "tailwindcss";
@import "./design-system/tokens.css";

@layer base {
  html {
    font-family: var(--font-sans);
    background: var(--sb-bg);
    color: var(--sb-text);
  }
  :focus-visible {
    outline: 2px solid var(--sb-focus-ring);
    outline-offset: 2px;
  }
  @media (prefers-reduced-motion: reduce) {
    *,
    *::before,
    *::after {
      transition-duration: 0.01ms !important;
      animation-duration: 0.01ms !important;
    }
  }
}
```

- [ ] **Step 6: Write the failing tests for both checkers**

`web/scripts/check-contrast.test.ts`:

```ts
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { checkTokens } from "./check-contrast.ts";

const tokensCss = readFileSync(new URL("../src/design-system/tokens.css", import.meta.url), "utf8");

describe("checkTokens", () => {
  it("passes for the real tokens in both themes", () => {
    const { failures, checked } = checkTokens(tokensCss);
    expect(failures).toEqual([]);
    expect(checked).toBeGreaterThan(100);
  });

  it("reports a low-contrast text pair with theme and ratio", () => {
    const css = `:root { --sb-bg: oklch(0.99 0 0); --sb-surface: oklch(0.97 0 0);
      --sb-surface-raised: oklch(1 0 0); --sb-text: oklch(0.8 0 0); --sb-text-muted: oklch(0.3 0 0);
      --sb-accent: oklch(0.4 0 0); --sb-accent-fg: oklch(0.99 0 0);
      --sb-border-input: oklch(0.5 0 0); --sb-focus-ring: oklch(0.5 0 0); }`;
    const { failures } = checkTokens(css);
    expect(failures.some((f) => f.theme === "light" && f.fg === "--sb-text" && f.min === 4.5)).toBe(
      true,
    );
  });

  it("resolves var() aliases before measuring", () => {
    const css = `:root { --sb-bg: oklch(0.99 0 0); --sb-surface: oklch(0.97 0 0);
      --sb-surface-raised: oklch(1 0 0); --sb-text: oklch(0.2 0 0); --sb-text-muted: oklch(0.4 0 0);
      --sb-accent: oklch(0.4 0 0); --sb-accent-fg: oklch(0.99 0 0);
      --sb-border-input: oklch(0.5 0 0); --sb-focus-ring: oklch(0.5 0 0);
      --sb-x-fg: oklch(0.95 0 0); --sb-x-bg: oklch(0.99 0 0); --sb-node-y-fg: var(--sb-x-fg);
      --sb-node-y-bg: var(--sb-x-bg); }`;
    const { failures } = checkTokens(css);
    expect(failures.some((f) => f.fg === "--sb-node-y-fg")).toBe(true);
  });

  it("fails on an unresolvable token", () => {
    const css = `:root { --sb-bg: oklch(0.99 0 0); --sb-text: var(--sb-missing); }`;
    expect(checkTokens(css).failures.length).toBeGreaterThan(0);
  });
});
```

`web/scripts/check-colors.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { findViolations } from "./check-colors.ts";

describe("findViolations", () => {
  it.each([
    `const c = "#ff0000";`,
    `<div className="bg-[#123456]" />`,
    `style={{ color: "rgb(1, 2, 3)" }}`,
    `color: oklch(0.5 0.1 200);`,
    `color: hsl(200 50% 50%);`,
  ])("flags %s", (source) => {
    expect(findViolations(source)).toHaveLength(1);
  });

  it.each([
    `<a href="#main-content">Skip</a>`,
    `<a href="#add-note">Add</a>`,
    `const label = "Step #12";`,
    `<div className="bg-surface text-fg" />`,
    `const text = label(1) + getLabel(2);`,
  ])("ignores %s", (source) => {
    expect(findViolations(source)).toEqual([]);
  });

  it("reports 1-based line numbers", () => {
    expect(findViolations(`ok\nok\ncolor: "#abcdef"`)[0]?.line).toBe(3);
  });
});
```

Run: `pnpm --dir web exec vitest run scripts`
Expected: FAIL (modules not found).

- [ ] **Step 7: Implement `web/scripts/check-contrast.ts`**

```ts
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { parse, wcagContrast } from "culori";

export type Failure = { theme: string; fg: string; bg: string; ratio: number; min: number };
type Vars = Map<string, string>;

const TEXT = 4.5;
const NON_TEXT = 3;
const BASE_PAIRS: Array<[string, string, number]> = [
  ["--sb-text", "--sb-bg", TEXT],
  ["--sb-text", "--sb-surface", TEXT],
  ["--sb-text", "--sb-surface-raised", TEXT],
  ["--sb-text-muted", "--sb-bg", TEXT],
  ["--sb-text-muted", "--sb-surface", TEXT],
  ["--sb-text-muted", "--sb-surface-raised", TEXT],
  ["--sb-accent-fg", "--sb-accent", TEXT],
  ["--sb-border-input", "--sb-bg", NON_TEXT],
  ["--sb-border-input", "--sb-surface", NON_TEXT],
  ["--sb-focus-ring", "--sb-bg", NON_TEXT],
  ["--sb-focus-ring", "--sb-surface", NON_TEXT],
];

function collect(css: string, selector: RegExp): Vars {
  const vars: Vars = new Map();
  for (const block of css.matchAll(selector)) {
    for (const match of (block[1] ?? "").matchAll(/(--sb-[\w-]+)\s*:\s*([^;]+);/g)) {
      const [, name, value] = match;
      if (name && value) vars.set(name, value.trim());
    }
  }
  return vars;
}

function resolveVar(name: string, vars: Vars, depth = 0): string | undefined {
  const value = vars.get(name);
  if (value === undefined || depth > 10) return undefined;
  const alias = /^var\((--sb-[\w-]+)\)$/.exec(value);
  return alias?.[1] ? resolveVar(alias[1], vars, depth + 1) : value;
}

function pairsFor(vars: Vars): Array<[string, string, number]> {
  const pairs = [...BASE_PAIRS];
  for (const name of vars.keys()) {
    if (name.endsWith("-fg") && name !== "--sb-accent-fg") {
      const prefix = name.slice(0, -3);
      if (vars.has(`${prefix}-bg`)) pairs.push([name, `${prefix}-bg`, TEXT]);
      pairs.push([name, "--sb-bg", TEXT], [name, "--sb-surface", TEXT]);
    }
    if (name.endsWith("-border") && name !== "--sb-border" && name !== "--sb-border-input") {
      pairs.push([name, "--sb-bg", NON_TEXT]);
    }
  }
  return pairs;
}

export function checkTokens(css: string): { failures: Failure[]; checked: number } {
  const clean = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const light = collect(clean, /:root\s*\{([^}]*)\}/g);
  const dark = new Map([...light, ...collect(clean, /\[data-theme="dark"\]\s*\{([^}]*)\}/g)]);
  const failures: Failure[] = [];
  let checked = 0;
  for (const [theme, vars] of [["light", light], ["dark", dark]] as const) {
    for (const [fg, bg, min] of pairsFor(vars)) {
      if (!vars.has(fg) || !vars.has(bg)) {
        if (BASE_PAIRS.some(([f, b]) => f === fg && b === bg)) {
          failures.push({ theme, fg, bg, ratio: 0, min });
        }
        continue;
      }
      checked += 1;
      const fgColor = parse(resolveVar(fg, vars) ?? "");
      const bgColor = parse(resolveVar(bg, vars) ?? "");
      const ratio = fgColor && bgColor ? wcagContrast(fgColor, bgColor) : 0;
      if (ratio < min) failures.push({ theme, fg, bg, ratio: Math.round(ratio * 100) / 100, min });
    }
  }
  return { failures, checked };
}

const isMain = process.argv[1] !== undefined && import.meta.url === pathToFileURL(resolve(process.argv[1])).href;
if (isMain) {
  const tokensPath = fileURLToPath(new URL("../src/design-system/tokens.css", import.meta.url));
  const { failures, checked } = checkTokens(readFileSync(tokensPath, "utf8"));
  for (const f of failures) {
    console.error(`[${f.theme}] ${f.fg} on ${f.bg}: ${f.ratio}:1 (needs ${f.min}:1)`);
  }
  console.log(`contrast: ${checked} pairs checked, ${failures.length} failing`);
  process.exit(failures.length > 0 ? 1 : 0);
}
```

- [ ] **Step 8: Implement `web/scripts/check-colors.ts`**

```ts
import { readdirSync, readFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

export type Violation = { line: number; text: string };

const PATTERNS = [
  /(?<![\w&/])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])/,
  /\b(?:rgba?|hsla?|oklch|oklab|lch|lab|hwb)\(/,
  /-\[(?:#|rgb|hsl|oklch|color:)/,
];
const SKIP_FILES = new Set(["tokens.css", "routeTree.gen.ts"]);

export function findViolations(source: string): Violation[] {
  return source.split(/\r?\n/).flatMap((text, index) =>
    PATTERNS.some((pattern) => pattern.test(text)) ? [{ line: index + 1, text: text.trim() }] : [],
  );
}

function* walk(dir: string): Generator<string> {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name !== "api") yield* walk(path);
    } else if (/\.(tsx?|css)$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) && !SKIP_FILES.has(entry.name)) {
      yield path;
    }
  }
}

const isMain = process.argv[1] !== undefined && import.meta.url === pathToFileURL(resolve(process.argv[1])).href;
if (isMain) {
  const src = fileURLToPath(new URL("../src", import.meta.url));
  let count = 0;
  for (const file of walk(src)) {
    for (const v of findViolations(readFileSync(file, "utf8"))) {
      count += 1;
      console.error(`${relative(src, file)}:${v.line}: color literal — use a token: ${v.text}`);
    }
  }
  console.log(`color guard: ${count} violation(s)`);
  process.exit(count > 0 ? 1 : 0);
}
```

- [ ] **Step 9: Run the checker tests**

Run: `pnpm --dir web exec vitest run scripts`
Expected: all pass. If the real-tokens test fails, the failure lists the exact pair. Do not loosen thresholds: fix the token value.

- [ ] **Step 10: Write `web/justfile` and register it**

```just
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

# Vite dev server (proxies /api to the backend)
dev:
    pnpm exec vite

# Production build into web/dist
build:
    pnpm exec vite build

# Lint, types, contrast and hardcoded-color checks
check:
    pnpm exec biome ci .
    pnpm exec tsr generate
    pnpm exec tsc --noEmit
    pnpm exec tsx scripts/check-contrast.ts
    pnpm exec tsx scripts/check-colors.ts

# Unit tests
test *args:
    pnpm exec vitest run {{ args }}

# End-to-end tests (starts API + Vite against the test database)
e2e *args:
    pnpm exec playwright test {{ args }}

# Format and auto-fix
fmt:
    pnpm exec biome check --write .
```

Root `justfile`: add `mod web` next to the other modules.

> `tsc` and `vite` fail until Task 10 creates `src/main.tsx` and routes. In this task, verify only the parts that exist (Step 11).

- [ ] **Step 11: Verify**

Run: `pnpm --dir web exec tsx scripts/check-contrast.ts`
Expected: `contrast: N pairs checked, 0 failing` with N > 100.
Run: `pnpm --dir web exec tsx scripts/check-colors.ts`
Expected: `color guard: 0 violation(s)`.
Run: `pnpm --dir web exec biome ci .`
Expected: no errors. Run `just web::fmt` first if only formatting differs.

- [ ] **Step 12: Commit**

```bash
git add -A
git commit -m "feat(web): scaffold Vite app with design tokens" -m "Add WCAG contrast and hardcoded-color checks for tokens.css."
```

---

### Task 9: Generated API client and auth client logic

**Files:**
- Create: `web/src/api/openapi.json` and `web/src/api/schema.d.ts` (both generated), `web/src/api/client.ts`, `web/src/api/client.test.ts`, `web/src/features/auth/session.ts`, `web/src/features/auth/session.test.ts`
- Modify: root `justfile` (`api-client`, `api-client-check`)

**Interfaces:**
- Consumes: the `ai-second-brain openapi --output` command (Task 7).
- Produces:
  - `api` (openapi-fetch client typed with `paths`), `setUnauthorizedHandler(handler: () => void): void`, `unauthorizedMiddleware: Middleware`.
  - `SessionInfo`, `sessionQueryKey`, `fetchSession(): Promise<SessionInfo | null>`, `sessionQueryOptions`.
  - `LoginResult` union, `interpretLoginResponse(status: number, retryAfter: string | null): LoginResult`, `login(password): Promise<LoginResult>`, `logout(): Promise<void>`, `safeRedirect(target: unknown): string`.

- [ ] **Step 1: Add the generation recipes to the root `justfile`**

```just
# Regenerate the TypeScript API client from the backend OpenAPI schema
api-client:
    uv run --directory backend ai-second-brain openapi --output ../web/src/api/openapi.json
    pnpm --dir web exec openapi-typescript src/api/openapi.json --output src/api/schema.d.ts

# Fail if the committed API client differs from the backend
api-client-check: api-client
    git diff --exit-code -- web/src/api
```

Run: `just api-client`
Expected: both files are created. `schema.d.ts` contains `"/api/auth/login"` and `MeResponse`.

- [ ] **Step 2: Write the failing tests**

`web/src/api/client.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest";
import { setUnauthorizedHandler, unauthorizedMiddleware } from "./client";

async function respond(path: string, status: number): Promise<void> {
  const request = new Request(`http://localhost${path}`);
  const response = new Response(null, { status });
  // biome-ignore lint/suspicious/noExplicitAny: middleware params are library-internal
  await unauthorizedMiddleware.onResponse?.({ request, response } as any);
}

describe("unauthorizedMiddleware", () => {
  it("calls the handler on 401 from ordinary endpoints", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    await respond("/api/search", 401);
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it.each(["/api/auth/me", "/api/auth/login"])("ignores 401 from %s", async (path) => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    await respond(path, 401);
    expect(handler).not.toHaveBeenCalled();
  });

  it("ignores other statuses", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    await respond("/api/search", 500);
    expect(handler).not.toHaveBeenCalled();
  });
});
```

`web/src/features/auth/session.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { interpretLoginResponse, safeRedirect } from "./session";

describe("interpretLoginResponse", () => {
  it.each([
    [204, null, { ok: true }],
    [401, null, { ok: false, reason: "invalid" }],
    [422, null, { ok: false, reason: "invalid" }],
    [429, "42", { ok: false, reason: "throttled", retryAfter: 42 }],
    [429, null, { ok: false, reason: "throttled", retryAfter: 60 }],
    [429, "soon", { ok: false, reason: "throttled", retryAfter: 60 }],
    [503, null, { ok: false, reason: "unreachable" }],
    [500, null, { ok: false, reason: "unreachable" }],
    [403, null, { ok: false, reason: "unreachable" }],
  ] as const)("status %i (Retry-After %s)", (status, retryAfter, expected) => {
    expect(interpretLoginResponse(status, retryAfter)).toEqual(expected);
  });
});

describe("safeRedirect", () => {
  it.each([
    ["/search", "/search"],
    ["/projects?x=1#y", "/projects?x=1#y"],
    [undefined, "/ask"],
    [42, "/ask"],
    ["", "/ask"],
    ["https://evil.example", "/ask"],
    ["//evil.example", "/ask"],
    ["/\\evil.example", "/ask"],
    ["/login", "/ask"],
    ["/login?redirect=/x", "/ask"],
    ["javascript:alert(1)", "/ask"],
  ])("%s → %s", (input, expected) => {
    expect(safeRedirect(input)).toBe(expected);
  });
});
```

Run: `pnpm --dir web exec vitest run src`
Expected: FAIL (modules missing).

- [ ] **Step 3: Implement `web/src/api/client.ts`**

```ts
import createClient, { type Middleware } from "openapi-fetch";
import type { paths } from "./schema";

const IGNORED_401_PATHS = new Set(["/api/auth/me", "/api/auth/login"]);

let onUnauthorized: (() => void) | undefined;

/** Called when any request other than me/login gets a 401 (the session ended). */
export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler;
}

export const unauthorizedMiddleware: Middleware = {
  onResponse({ request, response }) {
    const path = new URL(request.url).pathname;
    if (response.status === 401 && !IGNORED_401_PATHS.has(path)) onUnauthorized?.();
    return undefined;
  },
};

export const api = createClient<paths>({
  baseUrl: globalThis.location?.origin ?? "",
  credentials: "same-origin",
});
api.use(unauthorizedMiddleware);
```

- [ ] **Step 4: Implement `web/src/features/auth/session.ts`**

```ts
import { queryOptions } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { components } from "@/api/schema";

export type SessionInfo = components["schemas"]["MeResponse"];
export const sessionQueryKey = ["auth", "session"] as const;

export async function fetchSession(): Promise<SessionInfo | null> {
  const { data, response } = await api.GET("/api/auth/me");
  if (response.status === 401) return null;
  if (!data) throw new Error(`Session check failed with status ${response.status}`);
  return data;
}

export const sessionQueryOptions = queryOptions({
  queryKey: sessionQueryKey,
  queryFn: fetchSession,
  staleTime: 60_000,
  retry: false,
});

export type LoginResult =
  | { ok: true }
  | { ok: false; reason: "invalid" }
  | { ok: false; reason: "throttled"; retryAfter: number }
  | { ok: false; reason: "unreachable" };

export function interpretLoginResponse(status: number, retryAfter: string | null): LoginResult {
  if (status === 204) return { ok: true };
  if (status === 401 || status === 422) return { ok: false, reason: "invalid" };
  if (status === 429) {
    const seconds = Number.parseInt(retryAfter ?? "", 10);
    return { ok: false, reason: "throttled", retryAfter: Number.isFinite(seconds) && seconds > 0 ? seconds : 60 };
  }
  return { ok: false, reason: "unreachable" };
}

export async function login(password: string): Promise<LoginResult> {
  try {
    const { response } = await api.POST("/api/auth/login", { body: { password } });
    return interpretLoginResponse(response.status, response.headers.get("Retry-After"));
  } catch {
    return { ok: false, reason: "unreachable" };
  }
}

export async function logout(): Promise<void> {
  try {
    await api.POST("/api/auth/logout");
  } catch {
    // Logging out while offline still clears local state; the cookie expires server-side.
  }
}

/** Only same-app relative paths are allowed as post-login destinations (no open redirects). */
export function safeRedirect(target: unknown): string {
  if (typeof target !== "string") return "/ask";
  if (!target.startsWith("/") || target.startsWith("//") || target.startsWith("/\\")) return "/ask";
  if (target === "/login" || target.startsWith("/login?") || target.startsWith("/login/")) return "/ask";
  return target;
}
```

- [ ] **Step 5: Run the tests**

Run: `pnpm --dir web exec vitest run src`
Expected: all pass.

- [ ] **Step 6: Verify the staleness check**

Run: `git add web/src/api`, then `just api-client-check`
Expected: exit 0. Temporarily change `max_length=1024` to `1000` in `schemas.py`, then run `just api-client-check`. Expected: non-zero exit with a diff. Revert the change, regenerate, and confirm exit 0.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(web): add generated API client and auth logic"
```

---

### Task 10: Theme, primitives, app shell, routes and login

**Files:**
- Create: `web/src/design-system/theme.tsx`, `web/src/design-system/theme.test.tsx`, `web/src/design-system/ui/button.tsx`, `web/src/design-system/ui/input.tsx`, `web/src/design-system/ui/label.tsx`, `web/src/design-system/ui/card.tsx`, `web/src/design-system/AppShell.tsx`, `web/src/features/screens/screens.ts`, `web/src/features/screens/PlaceholderScreen.tsx`, `web/src/features/auth/LoginForm.tsx`, `web/src/features/auth/LoginForm.test.tsx`, `web/src/features/auth/guard.ts`, `web/src/features/auth/guard.test.ts`, `web/src/routes/__root.tsx`, `web/src/routes/index.tsx`, `web/src/routes/login.tsx`, `web/src/routes/_app.tsx`, `web/src/routes/_app/{ask,search,projects,digest,review,nodes,sources,settings}.tsx`, `web/src/main.tsx`, `web/src/routeTree.gen.ts` (generated)

**Interfaces:**
- Consumes: `api`, `setUnauthorizedHandler`, `sessionQueryOptions`, `sessionQueryKey`, `login`, `logout`, `safeRedirect`, `LoginResult` (Task 9); `cn` and the tokens (Task 8).
- Produces:
  - `ThemeProvider`, `useTheme()`, `ThemeToggle`, `applyStoredTheme()`, `resolveTheme(pref, prefersDark)` and `ThemePreference`.
  - `Button`, `Input`, `Label`, `Card`.
  - `AppShell({ children, onLogout })`, `SCREENS`, `NAV_ORDER`, `ScreenId`, `PlaceholderScreen({ id })`.
  - `LoginForm({ onSuccess, submit? })` and `loginErrorMessage(result)`.
  - `requireSession(queryClient, href)`.
- Accessible names used by e2e (Task 11): the button "Sign in", the field label "Password", the button "Log out", the button name starting `Theme:`, navigation "Primary", and a screen heading equal to the screen label.

- [ ] **Step 1: Write the failing tests**

`web/src/design-system/theme.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { resolveTheme, ThemeProvider, ThemeToggle } from "./theme";

describe("resolveTheme", () => {
  it.each([
    ["light", false, "light"],
    ["dark", false, "dark"],
    ["system", true, "dark"],
    ["system", false, "light"],
  ] as const)("%s (prefersDark=%s) → %s", (pref, prefersDark, expected) => {
    expect(resolveTheme(pref, prefersDark)).toBe(expected);
  });
});

describe("ThemeToggle", () => {
  it("cycles system → light → dark → system and persists", async () => {
    const user = userEvent.setup();
    render(<ThemeProvider><ThemeToggle /></ThemeProvider>);
    const html = document.documentElement;
    expect(html.dataset.theme).toBe("light"); // system with matchMedia=false
    await user.click(screen.getByRole("button", { name: /^Theme: system/ }));
    expect(html.dataset.theme).toBe("light");
    expect(window.localStorage.getItem("sb-theme")).toBe("light");
    await user.click(screen.getByRole("button", { name: /^Theme: light/ }));
    expect(html.dataset.theme).toBe("dark");
    await user.click(screen.getByRole("button", { name: /^Theme: dark/ }));
    expect(screen.getByRole("button", { name: /^Theme: system/ })).toBeInTheDocument();
  });

  it("survives a throwing localStorage", async () => {
    const getItem = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const user = userEvent.setup();
    render(<ThemeProvider><ThemeToggle /></ThemeProvider>);
    await user.click(screen.getByRole("button", { name: /^Theme: system/ }));
    expect(document.documentElement.dataset.theme).toBe("light");
    getItem.mockRestore();
    setItem.mockRestore();
  });
});
```

`web/src/features/auth/LoginForm.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { LoginForm } from "./LoginForm";
import type { LoginResult } from "./session";

async function submitWith(result: LoginResult) {
  const onSuccess = vi.fn();
  const user = userEvent.setup();
  render(<LoginForm onSuccess={onSuccess} submit={async () => result} />);
  await user.type(screen.getByLabelText("Password"), "hunter2");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  return onSuccess;
}

describe("LoginForm", () => {
  it("calls onSuccess on ok", async () => {
    const onSuccess = await submitWith({ ok: true });
    expect(onSuccess).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it.each([
    [{ ok: false, reason: "invalid" } as const, "Incorrect password"],
    [{ ok: false, reason: "throttled", retryAfter: 42 } as const, "Too many attempts, try again in 42 s"],
    [{ ok: false, reason: "unreachable" } as const, "Can't reach the server"],
  ])("shows an alert for %o", async (result, message) => {
    const onSuccess = await submitWith(result);
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("shows a pending state and ignores double submit", async () => {
    let resolveLogin: (r: LoginResult) => void = () => {};
    const submit = vi.fn(() => new Promise<LoginResult>((resolve) => { resolveLogin = resolve; }));
    const user = userEvent.setup();
    render(<LoginForm onSuccess={vi.fn()} submit={submit} />);
    await user.type(screen.getByLabelText("Password"), "pw");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    const pending = screen.getByRole("button", { name: "Signing in…" });
    expect(pending).toBeDisabled();
    await user.click(pending);
    expect(submit).toHaveBeenCalledTimes(1);
    resolveLogin({ ok: false, reason: "invalid" });
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeEnabled();
  });

  it("password field is labelled and uses current-password autocomplete", () => {
    render(<LoginForm onSuccess={vi.fn()} />);
    const input = screen.getByLabelText("Password");
    expect(input).toHaveAttribute("type", "password");
    expect(input).toHaveAttribute("autocomplete", "current-password");
    expect(input).toHaveAttribute("maxlength", "1024");
  });
});
```

`web/src/features/auth/guard.test.ts`:

```ts
import { QueryClient } from "@tanstack/react-query";
import { isRedirect } from "@tanstack/react-router";
import { describe, expect, it } from "vitest";
import { requireSession } from "./guard";
import { sessionQueryKey } from "./session";

describe("requireSession", () => {
  it("throws a redirect to /login carrying the original location", async () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(sessionQueryKey, null);
    const error = await requireSession(queryClient, "/nodes?x=1").catch((e: unknown) => e);
    expect(isRedirect(error)).toBe(true);
    expect((error as { options: { to: string; search: { redirect: string } } }).options).toMatchObject({
      to: "/login",
      search: { redirect: "/nodes?x=1" },
    });
  });

  it("resolves when a session exists", async () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(sessionQueryKey, { authenticated: true, expires_at: "2026-10-13T00:00:00Z" });
    await expect(requireSession(queryClient, "/ask")).resolves.toBeUndefined();
  });
});
```

Run: `pnpm --dir web exec vitest run src`
Expected: FAIL (modules missing).

- [ ] **Step 2: Implement the primitives**

`web/src/design-system/ui/button.tsx`:

```tsx
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps } from "react";
import { cn } from "@/design-system/cn";

export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-md text-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-60 [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary: "bg-accent text-accent-fg hover:opacity-90",
        outline: "border border-border-input bg-surface-raised text-fg hover:bg-surface",
        ghost: "text-fg hover:bg-surface",
      },
      size: { md: "h-10 px-4", sm: "h-8 px-3", icon: "size-10" },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

type ButtonProps = ComponentProps<"button"> & VariantProps<typeof buttonVariants> & { asChild?: boolean };

export function Button({ className, variant, size, asChild = false, type, ...props }: ButtonProps) {
  const Component = asChild ? Slot : "button";
  return (
    <Component
      className={cn(buttonVariants({ variant, size }), className)}
      type={asChild ? type : (type ?? "button")}
      {...props}
    />
  );
}
```

`web/src/design-system/ui/input.tsx`:

```tsx
import type { ComponentProps } from "react";
import { cn } from "@/design-system/cn";

export function Input({ className, ...props }: ComponentProps<"input">) {
  return (
    <input
      className={cn(
        "h-10 w-full rounded-md border border-border-input bg-surface-raised px-3 text-sm text-fg placeholder:text-fg-muted",
        className,
      )}
      {...props}
    />
  );
}
```

`web/src/design-system/ui/label.tsx`:

```tsx
import * as LabelPrimitive from "@radix-ui/react-label";
import type { ComponentProps } from "react";
import { cn } from "@/design-system/cn";

export function Label({ className, ...props }: ComponentProps<typeof LabelPrimitive.Root>) {
  return <LabelPrimitive.Root className={cn("text-sm font-medium text-fg", className)} {...props} />;
}
```

`web/src/design-system/ui/card.tsx`:

```tsx
import type { ComponentProps } from "react";
import { cn } from "@/design-system/cn";

export function Card({ className, ...props }: ComponentProps<"section">) {
  return (
    <section
      className={cn("rounded-lg border border-border bg-surface-raised p-6 text-fg", className)}
      {...props}
    />
  );
}
```

- [ ] **Step 3: Implement `web/src/design-system/theme.tsx`**

```tsx
import { Monitor, Moon, Sun } from "lucide-react";
import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { Button } from "./ui/button";

export type ThemePreference = "system" | "light" | "dark";
type ResolvedTheme = "light" | "dark";

const STORAGE_KEY = "sb-theme";
const NEXT: Record<ThemePreference, ThemePreference> = { system: "light", light: "dark", dark: "system" };
const DARK_QUERY = "(prefers-color-scheme: dark)";

function readPreference(): ThemePreference {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    return value === "light" || value === "dark" || value === "system" ? value : "system";
  } catch {
    return "system";
  }
}

function writePreference(value: ThemePreference): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, value);
  } catch {
    // Storage blocked (private mode): the choice lasts for this page view only.
  }
}

export function resolveTheme(preference: ThemePreference, prefersDark: boolean): ResolvedTheme {
  if (preference === "system") return prefersDark ? "dark" : "light";
  return preference;
}

function applyTheme(theme: ResolvedTheme): void {
  document.documentElement.dataset.theme = theme;
}

/** Call once before React renders to avoid a light flash for dark-mode users. */
export function applyStoredTheme(): void {
  applyTheme(resolveTheme(readPreference(), window.matchMedia(DARK_QUERY).matches));
}

type ThemeContextValue = { preference: ThemePreference; setPreference: (value: ThemePreference) => void };
const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(readPreference);

  useEffect(() => {
    const media = window.matchMedia(DARK_QUERY);
    const update = () => applyTheme(resolveTheme(preference, media.matches));
    update();
    if (preference !== "system") return;
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [preference]);

  const setPreference = useCallback((value: ThemePreference) => {
    writePreference(value);
    setPreferenceState(value);
  }, []);

  const value = useMemo(() => ({ preference, setPreference }), [preference, setPreference]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme must be used inside ThemeProvider");
  return context;
}

export function ThemeToggle() {
  const { preference, setPreference } = useTheme();
  const Icon = preference === "light" ? Sun : preference === "dark" ? Moon : Monitor;
  const label = `Theme: ${preference}. Switch to ${NEXT[preference]}`;
  return (
    <Button variant="ghost" size="icon" aria-label={label} title={label} onClick={() => setPreference(NEXT[preference])}>
      <Icon aria-hidden />
    </Button>
  );
}
```

- [ ] **Step 4: Implement the screens registry and placeholder**

`web/src/features/screens/screens.ts`:

```ts
import {
  FolderKanban,
  GitPullRequest,
  Library,
  type LucideIcon,
  MessageSquare,
  Search,
  Server,
  Settings,
  Sunrise,
} from "lucide-react";

export type ScreenId = "ask" | "search" | "projects" | "digest" | "review" | "nodes" | "sources" | "settings";

type Screen = {
  path: `/${ScreenId}`;
  label: string;
  icon: LucideIcon;
  phase: string;
  purpose: string;
};

export const SCREENS: Record<ScreenId, Screen> = {
  ask: { path: "/ask", label: "Ask", icon: MessageSquare, phase: "1b", purpose: "Ask questions answered from your private memory, with sources shown first." },
  search: { path: "/search", label: "Search", icon: Search, phase: "2", purpose: "Find notes and documents without generating an answer." },
  projects: { path: "/projects", label: "Projects", icon: FolderKanban, phase: "8", purpose: "Resume any project: decisions, commits, open threads and where it runs." },
  digest: { path: "/digest", label: "Digest", icon: Sunrise, phase: "4", purpose: "Your morning summary: new links, items to review and rediscovered ideas." },
  review: { path: "/review", label: "Review", icon: GitPullRequest, phase: "4", purpose: "Accept or reject the links proposed by nightly consolidation." },
  nodes: { path: "/nodes", label: "Nodes", icon: Server, phase: "5", purpose: "See and wake your machines: workstation, MacBook and Proxmox." },
  sources: { path: "/sources", label: "Sources", icon: Library, phase: "2", purpose: "Ingestion status, sharing and pinning for every source." },
  settings: { path: "/settings", label: "Settings", icon: Settings, phase: "1b", purpose: "Models, hosts, schedules and your login." },
};

export const NAV_ORDER: ScreenId[] = ["ask", "search", "projects", "digest", "review", "nodes", "sources", "settings"];
```

If any icon name no longer exists in the installed lucide-react, `tsc` reports it. Replace it with the closest icon from lucide.dev and keep the rest unchanged.

`web/src/features/screens/PlaceholderScreen.tsx`:

```tsx
import { Card } from "@/design-system/ui/card";
import { SCREENS, type ScreenId } from "./screens";

export function PlaceholderScreen({ id }: { id: ScreenId }) {
  const screen = SCREENS[id];
  const Icon = screen.icon;
  return (
    <Card className="max-w-2xl">
      <div className="flex items-center gap-3">
        <Icon aria-hidden className="size-6 text-fg-muted" />
        <h1 className="text-2xl font-semibold">{screen.label}</h1>
      </div>
      <p className="mt-3 text-fg-muted">{screen.purpose}</p>
      <p className="mt-4 text-sm font-medium">Arrives in phase {screen.phase}</p>
    </Card>
  );
}
```

- [ ] **Step 5: Implement `AppShell.tsx`**

```tsx
import { Link } from "@tanstack/react-router";
import { LogOut } from "lucide-react";
import type { ReactNode } from "react";
import { NAV_ORDER, SCREENS } from "@/features/screens/screens";
import { cn } from "./cn";
import { ThemeToggle } from "./theme";
import { Button } from "./ui/button";

function NavLinks({ layout }: { layout: "sidebar" | "bar" }) {
  return (
    <ul className={cn(layout === "sidebar" ? "flex flex-col gap-1 px-2" : "flex justify-between overflow-x-auto px-1")}>
      {NAV_ORDER.map((id) => {
        const screen = SCREENS[id];
        const Icon = screen.icon;
        return (
          <li key={id}>
            <Link
              to={screen.path}
              className={cn(
                "flex items-center rounded-md text-fg-muted hover:bg-surface-raised hover:text-fg",
                layout === "sidebar" ? "gap-3 px-3 py-2 text-sm" : "min-w-12 flex-col gap-1 px-2 py-2 text-xs",
              )}
              activeProps={{ className: "bg-accent text-accent-fg hover:bg-accent hover:text-accent-fg", "aria-current": "page" }}
            >
              <Icon aria-hidden className="size-4" />
              <span>{screen.label}</span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

export function AppShell({ children, onLogout }: { children: ReactNode; onLogout: () => void }) {
  return (
    <div className="min-h-dvh bg-bg text-fg md:grid md:grid-cols-[14rem_1fr]">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-surface-raised focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      <aside className="hidden border-r border-border bg-surface md:block">
        <div className="px-5 py-4 font-semibold">Second Brain</div>
        <nav aria-label="Primary">
          <NavLinks layout="sidebar" />
        </nav>
      </aside>
      <div className="flex min-h-dvh flex-col pb-20 md:pb-0">
        <header className="flex items-center justify-between border-b border-border px-4 py-2">
          <span className="font-semibold md:invisible">Second Brain</span>
          <div className="flex items-center gap-1">
            <ThemeToggle />
            <Button variant="ghost" size="sm" onClick={onLogout}>
              <LogOut aria-hidden />
              Log out
            </Button>
          </div>
        </header>
        <main id="main-content" tabIndex={-1} className="flex-1 p-4 md:p-8">
          {children}
        </main>
      </div>
      <nav aria-label="Primary" className="fixed inset-x-0 bottom-0 border-t border-border bg-surface md:hidden">
        <NavLinks layout="bar" />
      </nav>
    </div>
  );
}
```

- [ ] **Step 6: Implement the login form and guard**

`web/src/features/auth/LoginForm.tsx`:

```tsx
import { type FormEvent, useId, useState } from "react";
import { Button } from "@/design-system/ui/button";
import { Input } from "@/design-system/ui/input";
import { Label } from "@/design-system/ui/label";
import { type LoginResult, login } from "./session";

type Failure = Exclude<LoginResult, { ok: true }>;

export function loginErrorMessage(result: Failure): string {
  switch (result.reason) {
    case "invalid":
      return "Incorrect password";
    case "throttled":
      return `Too many attempts, try again in ${result.retryAfter} s`;
    case "unreachable":
      return "Can't reach the server";
  }
}

type LoginFormProps = {
  onSuccess: () => void | Promise<void>;
  submit?: (password: string) => Promise<LoginResult>;
};

export function LoginForm({ onSuccess, submit = login }: LoginFormProps) {
  const passwordId = useId();
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setError(null);
    const result = await submit(password);
    setPending(false);
    if (result.ok) {
      await onSuccess();
      return;
    }
    setError(loginErrorMessage(result));
  }

  return (
    <form className="flex flex-col gap-4" onSubmit={handleSubmit} noValidate>
      <div className="flex flex-col gap-2">
        <Label htmlFor={passwordId}>Password</Label>
        <Input
          id={passwordId}
          type="password"
          autoComplete="current-password"
          maxLength={1024}
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
      </div>
      {error !== null && (
        <p role="alert" className="rounded-md border border-danger-border bg-danger-bg px-3 py-2 text-sm text-danger-fg">
          {error}
        </p>
      )}
      <Button type="submit" disabled={pending} aria-disabled={pending}>
        {pending ? "Signing in…" : "Sign in"}
      </Button>
    </form>
  );
}
```

`web/src/features/auth/guard.ts`:

```ts
import type { QueryClient } from "@tanstack/react-query";
import { redirect } from "@tanstack/react-router";
import { sessionQueryOptions } from "./session";

/** Throws a redirect to /login unless a session exists. Errors count as "no session". */
export async function requireSession(queryClient: QueryClient, href: string): Promise<void> {
  const session = await queryClient.ensureQueryData(sessionQueryOptions).catch(() => null);
  if (!session) throw redirect({ to: "/login", search: { redirect: href } });
}
```

- [ ] **Step 7: Implement the routes**

`web/src/routes/__root.tsx`:

```tsx
import type { QueryClient } from "@tanstack/react-query";
import { createRootRouteWithContext, Outlet } from "@tanstack/react-router";

export type RouterContext = { queryClient: QueryClient };

export const Route = createRootRouteWithContext<RouterContext>()({
  component: Outlet,
});
```

`web/src/routes/index.tsx`:

```tsx
import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/")({
  beforeLoad: () => {
    throw redirect({ to: "/ask" });
  },
});
```

`web/src/routes/login.tsx`:

```tsx
import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute, redirect, useRouter } from "@tanstack/react-router";
import { Card } from "@/design-system/ui/card";
import { LoginForm } from "@/features/auth/LoginForm";
import { safeRedirect, sessionQueryKey, sessionQueryOptions } from "@/features/auth/session";

type LoginSearch = { redirect?: string };

export const Route = createFileRoute("/login")({
  validateSearch: (search: Record<string, unknown>): LoginSearch =>
    typeof search.redirect === "string" ? { redirect: search.redirect } : {},
  beforeLoad: async ({ context, search }) => {
    const session = await context.queryClient.ensureQueryData(sessionQueryOptions).catch(() => null);
    if (session) throw redirect({ href: safeRedirect(search.redirect) });
  },
  component: LoginPage,
});

function LoginPage() {
  const { redirect: target } = Route.useSearch();
  const queryClient = useQueryClient();
  const router = useRouter();

  async function handleSuccess() {
    await queryClient.invalidateQueries({ queryKey: sessionQueryKey });
    await router.navigate({ href: safeRedirect(target) });
  }

  return (
    <div className="grid min-h-dvh place-items-center bg-bg p-4 text-fg">
      <Card className="w-full max-w-sm">
        <h1 className="mb-1 text-xl font-semibold">Second Brain</h1>
        <p className="mb-6 text-sm text-fg-muted">Sign in to your private memory.</p>
        <LoginForm onSuccess={handleSuccess} />
      </Card>
    </div>
  );
}
```

If `redirect({ href })` or `router.navigate({ href })` fails to type-check with the installed router version, use `router.history.push(safeRedirect(target))` for navigation, and `throw redirect({ to: "/ask" })` in `beforeLoad`. Keep `safeRedirect` in the path.

`web/src/routes/_app.tsx`:

```tsx
import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute, Outlet, useNavigate } from "@tanstack/react-router";
import { AppShell } from "@/design-system/AppShell";
import { requireSession } from "@/features/auth/guard";
import { logout, sessionQueryKey } from "@/features/auth/session";

export const Route = createFileRoute("/_app")({
  beforeLoad: ({ context, location }) => requireSession(context.queryClient, location.href),
  component: AppLayout,
});

function AppLayout() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  async function handleLogout() {
    await logout();
    queryClient.setQueryData(sessionQueryKey, null);
    await navigate({ to: "/login", search: {} });
  }

  return (
    <AppShell onLogout={handleLogout}>
      <Outlet />
    </AppShell>
  );
}
```

Create the eight screen routes. Each file follows this exact pattern with its own id. For example, `web/src/routes/_app/ask.tsx`:

```tsx
import { createFileRoute } from "@tanstack/react-router";
import { PlaceholderScreen } from "@/features/screens/PlaceholderScreen";

export const Route = createFileRoute("/_app/ask")({
  component: () => <PlaceholderScreen id="ask" />,
});
```

The other seven are identical apart from the path and id:

| File | `createFileRoute(...)` | `id` |
|---|---|---|
| `_app/search.tsx` | `"/_app/search"` | `"search"` |
| `_app/projects.tsx` | `"/_app/projects"` | `"projects"` |
| `_app/digest.tsx` | `"/_app/digest"` | `"digest"` |
| `_app/review.tsx` | `"/_app/review"` | `"review"` |
| `_app/nodes.tsx` | `"/_app/nodes"` | `"nodes"` |
| `_app/sources.tsx` | `"/_app/sources"` | `"sources"` |
| `_app/settings.tsx` | `"/_app/settings"` | `"settings"` |

- [ ] **Step 8: Implement `web/src/main.tsx`**

```tsx
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "./index.css";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRouter, RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { setUnauthorizedHandler } from "./api/client";
import { applyStoredTheme, ThemeProvider } from "./design-system/theme";
import { sessionQueryKey } from "./features/auth/session";
import { routeTree } from "./routeTree.gen";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

const router = createRouter({ routeTree, context: { queryClient }, defaultPreload: "intent" });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

setUnauthorizedHandler(() => {
  queryClient.setQueryData(sessionQueryKey, null);
  void router.invalidate();
});

applyStoredTheme();

const rootElement = document.getElementById("root");
if (!rootElement) throw new Error("Missing #root element");

createRoot(rootElement).render(
  <StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
);
```

- [ ] **Step 9: Generate routes, run tests and checks**

Run: `pnpm --dir web exec tsr generate`
Expected: `web/src/routeTree.gen.ts` is created.
Run: `just web::test`
Expected: all pass.
Run: `just web::fmt`, then `just web::check`
Expected: biome, tsc, contrast and color guard all pass. The plan's snippets are not pre-formatted to Biome's 100-column style, so `fmt` rewraps them first. Fix any type errors in your code. Do not relax `tsconfig`.

- [ ] **Step 10: Manual check in the browser**

Run `just backend::serve --reload` in one terminal and `just web::dev` in another. Open `http://localhost:5173`.
Expected: it redirects to `/login`. A wrong password shows "Incorrect password", and the right one (from Task 7 Step 5) lands on `/ask` with the sidebar. The theme button cycles light/dark, and "Log out" returns you to `/login`. Narrow the window below 768 px: the bottom bar replaces the sidebar. Press Tab from the top: "Skip to content" appears first.

- [ ] **Step 11: Commit**

```bash
git add -A
git commit -m "feat(web): add app shell, routes and login page" -m "Include the theme toggle, UI primitives and the session guard."
```

---

### Task 11: E2E tests, developer recipes and README

**Files:**
- Create: `web/playwright.config.ts`, `web/tests/e2e/auth.spec.ts`
- Modify: root `justfile` (final version), `README.md` (rewrite)

**Interfaces:**
- Consumes: everything above; `.env.test` (Task 1).
- Produces: the final root recipes `setup`, `install`, `dev`, `check`, `test`, `test-unit`, `e2e`, `fmt`, `api-client`, `api-client-check` and `hash-password`.

- [ ] **Step 1: Write `web/playwright.config.ts`**

```ts
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { parseEnv } from "node:util";
import { defineConfig, devices } from "@playwright/test";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const testEnv = parseEnv(readFileSync(join(root, ".env.test"), "utf8"));
const apiPort = testEnv.SB_API_PORT ?? "8001";
const webPort = testEnv.SB_WEB_PORT ?? "5174";
const baseURL = `http://localhost:${webPort}`;

const inheritedEnv = Object.fromEntries(
  Object.entries(process.env).filter((entry): entry is [string, string] => entry[1] !== undefined),
);

// Explicit test values override anything just loaded from the developer's .env.
const serverEnv = {
  ...inheritedEnv,
  DATABASE_URL: testEnv.TEST_DATABASE_URL ?? "",
  SB_OWNER_PASSWORD_HASH: testEnv.SB_OWNER_PASSWORD_HASH ?? "",
  SB_ALLOWED_ORIGINS: baseURL,
  SB_API_PORT: apiPort,
  SB_WEB_PORT: webPort,
  SB_ENV: "dev",
  SB_COOKIE_SECURE: "false",
};

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: { baseURL, trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `uv run --directory ../backend ai-second-brain serve --port ${apiPort}`,
      url: `http://127.0.0.1:${apiPort}/api/health`,
      env: serverEnv,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: "pnpm exec vite",
      url: baseURL,
      env: serverEnv,
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
```

- [ ] **Step 2: Write `web/tests/e2e/auth.spec.ts`**

```ts
import { expect, test } from "@playwright/test";

const PASSWORD = "e2e-test-password"; // matches the committed test-only hash in .env.test

async function signIn(page: import("@playwright/test").Page, password: string) {
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

test("protected pages redirect to login and keep the destination", async ({ page }) => {
  await page.goto("/nodes");
  await expect(page).toHaveURL(/\/login\?redirect=/);
  await signIn(page, PASSWORD);
  await expect(page).toHaveURL(/\/nodes$/);
  await expect(page.getByRole("heading", { name: "Nodes" })).toBeVisible();
});

test("wrong password shows an error", async ({ page }) => {
  await page.goto("/login");
  await signIn(page, "definitely-wrong");
  await expect(page.getByRole("alert")).toHaveText("Incorrect password");
  await expect(page).toHaveURL(/\/login/);
});

test("login lands on Ask with navigation; theme toggles; logout returns to login", async ({ page }) => {
  await page.goto("/");
  await signIn(page, PASSWORD);
  await expect(page).toHaveURL(/\/ask$/);
  await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Ask" })).toHaveAttribute("aria-current", "page");

  const html = page.locator("html");
  await page.getByRole("button", { name: /^Theme:/ }).click();
  await expect(html).toHaveAttribute("data-theme", "light");
  await page.getByRole("button", { name: /^Theme:/ }).click();
  await expect(html).toHaveAttribute("data-theme", "dark");

  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/login/);
  await page.goto("/ask");
  await expect(page).toHaveURL(/\/login/);
});

test("open-redirect targets are ignored after login", async ({ page }) => {
  await page.goto("/login?redirect=https://evil.example");
  await signIn(page, PASSWORD);
  await expect(page).toHaveURL(/\/ask$/);
});
```

- [ ] **Step 3: Run the e2e tests**

Prerequisite: `just db::up` and `just db::test-prepare` have been run.
Run: `just web::e2e`
Expected: `4 passed`. If a test fails, open `web/test-results/**/trace.zip` with `pnpm --dir web exec playwright show-trace <path>`.

- [ ] **Step 4: Write the final root `justfile`**

```just
set dotenv-load
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

mod backend
mod web
mod db

# List all recipes
default:
    @just --list --list-submodules

# Install Python + JavaScript dependencies and the Playwright browser
install:
    uv sync --directory backend
    pnpm install
    pnpm --dir web exec playwright install chromium

# First-time setup: dependencies, .env, database and migrations (Docker must be running)
setup: install
    pnpm exec tsx scripts/init-env.ts
    just db::up
    just db::migrate
    just db::test-prepare
    @echo "Setup complete. Next: run 'just hash-password', paste the line into .env, then 'just dev'."

# Run API (reload) and web dev server together; open http://localhost:5173
dev:
    just db::up
    pnpm exec concurrently --names api,web --prefix-colors blue,magenta --kill-others-on-fail "just backend::serve --reload" "just web::dev"

# All static checks (backend, web, API client, DB schema)
check:
    just backend::check
    just web::check
    just api-client-check
    just db::schema-check

# All tests (needs the database)
test:
    just backend::test
    just web::test

# Tests that need no database (macOS CI)
test-unit:
    just backend::test-unit
    just web::test

# End-to-end browser tests against the test database
e2e:
    just web::e2e

# Format and auto-fix everything
fmt:
    just backend::fmt
    just web::fmt

# Regenerate the TypeScript API client from the backend OpenAPI schema
api-client:
    uv run --directory backend ai-second-brain openapi --output ../web/src/api/openapi.json
    pnpm --dir web exec openapi-typescript src/api/openapi.json --output src/api/schema.d.ts

# Fail if the committed API client differs from the backend
api-client-check: api-client
    git diff --exit-code -- web/src/api

# Hash the owner password; paste the printed line into .env
hash-password:
    uv run --directory backend ai-second-brain hash-password
```

- [ ] **Step 5: Rewrite `README.md`**

````markdown
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
````

- [ ] **Step 6: Full local verification**

Run: `just check`, then `just test`, then `just e2e`
Expected: all green. `db::schema-check` prints `schema-check: OK`.
Run: `just dev` and log in once more in the browser. Stop it with Ctrl+C. Both processes exit because of `--kill-others-on-fail` or Ctrl+C.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: add e2e tests, dev recipes and README"
```

---

### Task 12: CI workflow (Linux full, macOS on push)

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: recipes `install`, `db::up`, `db::migrate`, `db::test-prepare`, `check`, `test`, `test-unit` and `e2e`.

- [ ] **Step 1: Write `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  linux:
    runs-on: ubuntu-latest
    timeout-minutes: 25
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@v6
      - uses: pnpm/action-setup@v4
      - uses: actions/setup-node@v5
        with:
          node-version: 24
          cache: pnpm
      - uses: extractions/setup-just@v3
      - name: Create .env from example
        run: cp .env.example .env
      - run: just install
      - name: Playwright system dependencies
        run: pnpm --dir web exec playwright install-deps chromium
      - run: just db::up
      - run: just db::migrate
      - run: just db::test-prepare
      - run: just check
      - run: just test
      - run: just e2e
      - uses: actions/upload-artifact@v4
        if: failure()
        with:
          name: playwright-traces
          path: web/test-results
          if-no-files-found: ignore

  macos:
    if: github.event_name == 'push'
    runs-on: macos-latest
    timeout-minutes: 25
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@v6
      - uses: pnpm/action-setup@v4
      - uses: actions/setup-node@v5
        with:
          node-version: 24
          cache: pnpm
      - uses: extractions/setup-just@v3
      - name: Create .env from example
        run: cp .env.example .env
      - run: just install
      - run: just check
      - run: just test-unit
```

Notes:
- `pnpm/action-setup@v4` reads the pnpm version from `packageManager` in the root `package.json`.
- On macOS, `just check` prints `schema-check: SKIPPED (no database)` because there is no Docker. That is expected.
- `.env` comes from `.env.example` with an empty owner hash. No CI step starts the dev API, and the tests and e2e use their own hashes.

- [ ] **Step 2: Validate locally what CI runs**

Run: `just install`, `just check`, `just test-unit`
Expected: green. This mirrors the macOS job.

- [ ] **Step 3: Commit, push and watch CI**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add Linux and macOS workflows" -m "Linux runs the full suite with Postgres; macOS runs checks and
unit tests on push to main."
git push origin main
```

Expected: both `linux` and `macos` jobs pass on the push. If one fails, read the log, fix, commit and push again. Do not mark the task done on red CI.

- [ ] **Step 4: Acceptance checklist (spec §13)**

- [ ] The MVP files are gone. The README explains setup in under 5 minutes of reading.
- [ ] On Windows, `just setup` completes and prints the next steps.
- [ ] `just dev` → browser login → shell with 8 placeholder screens, light/dark toggle, logout.
- [ ] `just check`, `just test` and `just e2e` pass locally.
- [ ] GitHub Actions: `linux` and `macos` jobs are green on the push to `main`.
- [ ] On the owner's M1 MacBook: `just setup`, `just dev` (browser login), `just check` and `just test` pass. The owner does this manually; record the result in the final summary.
- [ ] No recipe contains pipes, `&&`, redirects or OS-specific utilities (review every `justfile`).
- [ ] No hardcoded colors outside `tokens.css`, and the contrast check passes in both themes.
- [ ] No secrets committed: `.env` is ignored, and `.env.test` holds test-only values.

---

### Task 13: Automated SemVer releases (semantic-release)

Added 2026-09-29 at the owner's request. Spec §11.1 is binding. CI computes versions from Conventional Commits, tags `vX.Y.Z`, bumps the version files and publishes a GitHub Release with generated notes. Tags are never created by hand, except the one baseline tag the owner approved.

**Files:**
- Create: `.releaserc.json`, `scripts/lib/version.ts`, `scripts/lib/version.test.ts`, `scripts/set-version.ts`
- Modify: root `package.json` (devDependencies), `pnpm-lock.yaml`, `web/package.json` (gains `"version"`), root `justfile` (`test-scripts`, `test`, `test-unit`, `release-dry-run`), `.github/workflows/ci.yml` (workflow `permissions`, `release` job), `README.md` (Releases section)

**Interfaces:**
- Consumes: `repoRoot` from `scripts/lib/docker.ts` (Task 1); the CI jobs `linux` and `macos` (Task 12); the `[project]` table in `backend/pyproject.toml` (Task 3).
- Produces:
  - `scripts/lib/version.ts` exports `assertSemver(version: string): void`, `setPyprojectVersion(toml: string, version: string): string` and `setPackageJsonVersion(json: string, version: string): string`.
  - The CLI `tsx scripts/set-version.ts <X.Y.Z>`.
  - Release commits `chore(release): vX.Y.Z [skip ci]`.

- [ ] **Step 1: Install semantic-release at the workspace root**

```bash
pnpm add -D -w semantic-release @semantic-release/exec @semantic-release/git conventional-changelog-conventionalcommits
```

Expected: semantic-release 25.x. Its engines require Node `^22.14 || >=24.10`, which both CI's Node 24 and the local Node 25 satisfy. Apply the Task 1 Step 7 `allowBuilds` rule if pnpm reports ignored build scripts.

- [ ] **Step 2: Write the failing tests `scripts/lib/version.test.ts`** (Node's built-in test runner via tsx)

```ts
import assert from "node:assert/strict";
import { test } from "node:test";
import { assertSemver, setPackageJsonVersion, setPyprojectVersion } from "./version.ts";

const PYPROJECT = [
  "[project]",
  'name = "ai-second-brain"',
  'version = "0.2.0"',
  "",
  "[tool.other]",
  'version = "9.9.9"',
  "",
].join("\n");

test("setPyprojectVersion replaces only the [project] version", () => {
  const updated = setPyprojectVersion(PYPROJECT, "1.2.3");
  assert.match(updated, /\[project\]\nname = "ai-second-brain"\nversion = "1\.2\.3"\n/);
  assert.match(updated, /\[tool\.other\]\nversion = "9\.9\.9"/);
});

test("setPyprojectVersion throws when [project] has no version", () => {
  assert.throws(() => setPyprojectVersion('[project]\nname = "x"\n', "1.0.0"), /no \[project\] version/);
});

test("setPackageJsonVersion adds the version right after the name", () => {
  const updated = setPackageJsonVersion('{"name":"@x/web","private":true}', "0.2.0");
  assert.equal(updated, '{\n  "name": "@x/web",\n  "version": "0.2.0",\n  "private": true\n}\n');
});

test("setPackageJsonVersion replaces an existing version", () => {
  const updated = setPackageJsonVersion('{"name":"w","version":"0.1.0","type":"module"}', "0.3.0");
  assert.deepEqual(JSON.parse(updated), { name: "w", version: "0.3.0", type: "module" });
});

for (const bad of ["v1.2.3", "1.2", "latest", "", "1.2.3; rm -rf /"]) {
  test(`assertSemver rejects ${JSON.stringify(bad)}`, () => {
    assert.throws(() => assertSemver(bad), /Not a SemVer version/);
  });
}

test("assertSemver accepts release and pre-release versions", () => {
  assertSemver("0.2.0");
  assertSemver("1.0.0-rc.1");
});
```

Run: `pnpm exec tsx --test scripts/lib/version.test.ts`
Expected: FAIL (`Cannot find module './version.ts'`).

- [ ] **Step 3: Implement `scripts/lib/version.ts`**

```ts
const SEMVER = /^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/;

export function assertSemver(version: string): void {
  if (!SEMVER.test(version)) throw new Error(`Not a SemVer version: "${version}"`);
}

/** Replace `version = "..."` inside the [project] table only. */
export function setPyprojectVersion(toml: string, version: string): string {
  assertSemver(version);
  let inProject = false;
  let replaced = false;
  const lines = toml.split("\n").map((line) => {
    const table = /^\s*\[([^\]]+)\]\s*$/.exec(line);
    if (table) {
      inProject = table[1] === "project";
      return line;
    }
    if (inProject && !replaced && /^\s*version\s*=/.test(line)) {
      replaced = true;
      return `version = "${version}"`;
    }
    return line;
  });
  if (!replaced) throw new Error("pyproject.toml has no [project] version");
  return lines.join("\n");
}

/** Set "version" (placed right after "name"), keeping other keys and 2-space formatting. */
export function setPackageJsonVersion(json: string, version: string): string {
  assertSemver(version);
  const { name, version: _previous, ...rest } = JSON.parse(json) as Record<string, unknown>;
  return `${JSON.stringify({ name, version, ...rest }, null, 2)}\n`;
}
```

Run: `pnpm exec tsx --test scripts/lib/version.test.ts`
Expected: all tests pass.

- [ ] **Step 4: Write `scripts/set-version.ts`**

```ts
import { spawnSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { repoRoot } from "./lib/docker.ts";
import { assertSemver, setPackageJsonVersion, setPyprojectVersion } from "./lib/version.ts";

const version = process.argv[2] ?? "";
assertSemver(version);

function edit(relativePath: string, update: (text: string, version: string) => string): void {
  const path = join(repoRoot, relativePath);
  writeFileSync(path, update(readFileSync(path, "utf8"), version), "utf8");
}

edit("backend/pyproject.toml", setPyprojectVersion);
edit("web/package.json", setPackageJsonVersion);

const lock = spawnSync("uv", ["lock", "--directory", join(repoRoot, "backend")], { stdio: "inherit" });
if (lock.status !== 0) process.exit(lock.status ?? 1);
console.log(`Version set to ${version}`);
```

Verify it on a throwaway run, then revert:
Run: `pnpm exec tsx scripts/set-version.ts 9.9.9`, then `git diff --stat`
Expected: `backend/pyproject.toml`, `backend/uv.lock` and `web/package.json` changed, with `version = "9.9.9"` and `"version": "9.9.9"`.
Run: `git checkout -- backend/pyproject.toml backend/uv.lock web/package.json`
Run: `pnpm exec tsx scripts/set-version.ts v1`
Expected: exit non-zero with `Not a SemVer version: "v1"`, and no files changed.

- [ ] **Step 5: Write `.releaserc.json`**

```json
{
  "branches": ["main"],
  "tagFormat": "v${version}",
  "plugins": [
    ["@semantic-release/commit-analyzer", { "preset": "conventionalcommits" }],
    [
      "@semantic-release/release-notes-generator",
      {
        "preset": "conventionalcommits",
        "presetConfig": {
          "types": [
            { "type": "feat", "section": "🚀 Features" },
            { "type": "fix", "section": "🐛 Bug Fixes" },
            { "type": "perf", "section": "⚡ Performance" },
            { "type": "refactor", "section": "♻️ Refactoring", "hidden": true },
            { "type": "docs", "section": "📝 Documentation", "hidden": true },
            { "type": "test", "hidden": true },
            { "type": "ci", "hidden": true },
            { "type": "chore", "hidden": true },
            { "type": "style", "hidden": true }
          ]
        }
      }
    ],
    ["@semantic-release/exec", { "prepareCmd": "pnpm exec tsx scripts/set-version.ts ${nextRelease.version}" }],
    [
      "@semantic-release/git",
      {
        "assets": ["backend/pyproject.toml", "backend/uv.lock", "web/package.json"],
        "message": "chore(release): v${nextRelease.version} [skip ci]"
      }
    ],
    "@semantic-release/github"
  ]
}
```

Breaking changes appear under the preset's own "⚠ BREAKING CHANGES" heading. The release commit has no body and no attribution trailer.

- [ ] **Step 6: Add the version to `web/package.json` and the recipes**

Run: `pnpm exec tsx scripts/set-version.ts 0.1.0`, then `git checkout -- backend/pyproject.toml backend/uv.lock`
Expected: only `web/package.json` keeps its change. It now has `"version": "0.1.0"` after `"name"`. `backend/pyproject.toml` keeps `0.2.0`, which CI overwrites on the first release.

Root `justfile`: add the recipes below, and change `test` and `test-unit` so they also run `just test-scripts`:

```just
# Unit tests for the TypeScript helper scripts
test-scripts:
    pnpm exec tsx --test scripts/lib/version.test.ts

# Preview the next release locally (needs GITHUB_TOKEN; see README)
release-dry-run:
    pnpm exec semantic-release --dry-run --no-ci
```

```just
# All tests (needs the database)
test:
    just backend::test
    just web::test
    just test-scripts

# Tests that need no database (macOS CI)
test-unit:
    just backend::test-unit
    just web::test
    just test-scripts
```

- [ ] **Step 7: Add the release job to `.github/workflows/ci.yml`**

Below the `concurrency:` block, add the workflow-level default:

```yaml
permissions:
  contents: read
```

Append this job:

```yaml
  release:
    needs: [linux, macos]
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    timeout-minutes: 10
    permissions:
      contents: write
      issues: write
      pull-requests: write
    steps:
      - uses: actions/checkout@v5
        with:
          fetch-depth: 0
          persist-credentials: false
      - uses: astral-sh/setup-uv@v6
      - uses: pnpm/action-setup@v4
      - uses: actions/setup-node@v5
        with:
          node-version: 24
          cache: pnpm
      - run: pnpm install --frozen-lockfile
      - name: Release
        run: pnpm exec semantic-release
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

`[skip ci]` in the release commit and the fact that pushes made with `GITHUB_TOKEN` never trigger workflows together prevent release loops.

- [ ] **Step 8: Document releases in `README.md`**

Append:

````markdown
## Releases

Versions follow SemVer and are fully automated. After CI passes on `main`,
semantic-release reads the Conventional Commits since the last `v*` tag:

- `feat` bumps MINOR
- `fix` or `perf` bumps PATCH
- `BREAKING CHANGE:` or `type!:` bumps MAJOR
- other types alone do not release

It then updates the version files, commits `chore(release): vX.Y.Z [skip ci]`, tags
`vX.Y.Z`, and publishes a GitHub Release with generated notes.

- Never create, move or delete `v*` tags by hand. Fix forward with a new release.
- Recommended: protect `v*` tags in GitHub (Settings → Rules → Rulesets → Tag rules).
- Preview locally: set `GITHUB_TOKEN` (e.g. `$env:GITHUB_TOKEN = gh auth token` in
  PowerShell), then run `just release-dry-run`.
````

- [ ] **Step 9: Verify and commit**

Run: `just test-scripts`, then `just check`
Expected: all green.

```bash
git add -A
git commit -m "ci(release): automate SemVer releases" -m "Add semantic-release: CI derives the version from Conventional\nCommits, bumps version files, tags vX.Y.Z and publishes notes."
```

- [ ] **Step 10: Baseline tag and first release (controller runs this step with the owner's approval)**

Pushing a tag and pushing to `main` are outward actions. The controller confirms with the owner before running. **Push the tag before `main`:** if `main` reaches GitHub with the release job but without `v0.1.0`, semantic-release would publish `v1.0.0`.

```bash
git tag -a v0.1.0 14a68fb -m "v0.1.0: MVP baseline before the Phase 1a rebuild"
git push origin v0.1.0
git push origin main
```

Expected: CI runs `linux` and `macos`, then `release`. The release job creates `v0.2.0` from the Phase 1a `feat` commits. That means a GitHub Release with 🚀 Features notes, and a `chore(release): v0.2.0 [skip ci]` commit that bumps `backend/pyproject.toml`, `backend/uv.lock` and `web/package.json`. Run `git pull` afterwards to fetch the release commit.

If `release-dry-run` is used before this step, it should report the next version as 0.2.0 once `v0.1.0` exists locally.

<h1 align="center">🧠 AI Second Brain</h1>

<p align="center">
  <strong>A private-by-default memory for your notes, documents, code history and home lab.</strong><br>
  Self-hosted · local AI for private data · PostgreSQL + pgvector · web UI · runs on Windows, macOS and Linux
</p>

<p align="center">
  <a href="https://github.com/mdyzma/ai-second-brain/actions/workflows/ci.yml"><img src="https://github.com/mdyzma/ai-second-brain/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/mdyzma/ai-second-brain/releases/latest"><img src="https://img.shields.io/github/v/release/mdyzma/ai-second-brain?sort=semver" alt="Latest release"></a>
  <img src="https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white" alt="Python 3.12">
  <img src="https://img.shields.io/badge/node-24-339933?logo=node.js&logoColor=white" alt="Node 24">
  <img src="https://img.shields.io/badge/PostgreSQL-17%20%2B%20pgvector-4169E1?logo=postgresql&logoColor=white" alt="PostgreSQL 17 + pgvector">
  <img src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black" alt="React 19">
  <img src="https://img.shields.io/badge/uv%20%2B%20just-tooling-DE5FE9" alt="uv + just">
  <a href="https://www.conventionalcommits.org"><img src="https://img.shields.io/badge/commits-conventional-FE5196?logo=conventionalcommits&logoColor=white" alt="Conventional Commits"></a>
</p>

---

**AI Second Brain** collects the things you know into one searchable memory: Obsidian notes, documents,
invoices and contracts, email, git history, and the state of your home-lab machines. You can then ask it
questions and it answers with sources. That is the goal; today the platform and a private chat exist.
Private content is processed only by the Ollama endpoints you configure (on your own machines or LAN), and a
cloud model is used only when you explicitly choose it. It never reads your notes.

> **Status: Phase 2a "vault ingestion" (see the latest release badge above).** The platform is in place: a secure single-user
> login, the web app shell, the API, the database, CI and automated releases, plus the Ask screen
> for chatting with a local model. Your Obsidian vault is indexed in the background, but you can't search it or use it in chat yet (Phase 2b). The knowledge
> features arrive phase by phase; see the [roadmap](#roadmap). The screens show what each one
> will do.

## Contents

- [What it does today](#what-it-does-today)
- [Screenshots](#screenshots)
- [Roadmap](#roadmap)
- [Requirements](#requirements)
- [Quick start](#quick-start)
- [Everyday commands](#everyday-commands)
- [Repository layout](#repository-layout)
- [How it works](#how-it-works)
- [Configuration](#configuration)
- [Commit messages and releases](#commit-messages-and-releases)
- [Troubleshooting](#troubleshooting)
- [Documentation](#documentation)

## What it does today

| | |
| --- | --- |
| 💬 **Ask (private by default)** | Chat with a local Ollama model on your LAN; sources are shown before the answer; nothing is sent to the cloud. Cloud sessions (Anthropic) are an explicit, per-conversation opt-in and never read your notes. Retrieval arrives with Phase 2b, so answers currently say "No matching local sources". |
| 📚 **Vault ingestion** | The worker keeps an index of your Obsidian vault in Postgres (full-text immediately, bge-m3 vectors in the background), survives crashes and offline edits, and shows its state on the Sources screen. Search and using your notes in chat arrive in Phase 2b. |
| 🔐 **Single-owner login** | argon2id password hash, server-side sessions (only a SHA-256 of the token is stored), HttpOnly `SameSite=Strict` cookie, same-origin check on every write, lockout after 5 failed attempts, and protection against open redirects. |
| 🧭 **Web app shell** | React + TypeScript app with a sidebar on desktop and a bottom bar on phones. It has the eight screens of the product (Ask, Search, Projects, Digest, Review, Nodes, Sources, Settings) and a skip link, and it can be used from the keyboard alone. |
| 🌗 **Light and dark themes** | Follows your system or your choice. Every colour comes from design tokens, a check keeps all text at WCAG AA contrast in both themes, and another check blocks hard-coded colours. |
| 🗄️ **Database ready for vectors** | PostgreSQL 17 with the `pgvector` extension in Docker, versioned SQL migrations (dbmate), and a committed `db/schema.sql` that CI keeps honest. |
| 🔌 **Typed API** | FastAPI with health/readiness endpoints and auth. The TypeScript client is generated from the API schema, and CI fails if the two drift apart. |
| 🧪 **Tested end to end** | Python unit and integration tests against a real database, web unit tests, and Playwright browser tests of the login flow. In CI, Linux runs the full suite, including the database tests; macOS runs the checks and the tests that need no database. |
| 🚀 **Automated releases** | Versions and release notes come from the commit history (SemVer + semantic-release), with no manual tagging. |
| 🖥️ **Works on your machines** | The same `just` commands on Windows (PowerShell), macOS (Apple Silicon) and Linux. |

## Screenshots

![Ask screen](docs/images/readme/ask.jpg)

![Sources screen showing five indexed notes, all searchable, with embedding at 100%](docs/images/readme/sources.jpg)

<table>
  <tr>
    <th width="50%">Desktop, dark theme</th>
    <th width="50%">Desktop, light theme</th>
  </tr>
  <tr>
    <td><a href="docs/images/readme/app-dark.jpg"><img src="docs/images/readme/app-dark.jpg" alt="App shell in dark theme with the Ask screen"></a></td>
    <td><a href="docs/images/readme/app-light.jpg"><img src="docs/images/readme/app-light.jpg" alt="App shell in light theme with the Nodes screen"></a></td>
  </tr>
  <tr>
    <td>The sidebar holds the eight screens. Each placeholder says what the screen will do and which phase delivers it.</td>
    <td>The theme toggle in the header cycles between system, light and dark, and the choice is remembered.</td>
  </tr>
</table>

<table>
  <tr>
    <th width="62%">Sign in</th>
    <th width="38%">On a phone</th>
  </tr>
  <tr>
    <td><a href="docs/images/readme/login.jpg"><img src="docs/images/readme/login.jpg" alt="Login page showing the Incorrect password message"></a></td>
    <td><a href="docs/images/readme/app-mobile.jpg"><img src="docs/images/readme/app-mobile.jpg" alt="Mobile layout with the bottom navigation bar"></a></td>
  </tr>
  <tr>
    <td>One password for the owner. Errors are announced to screen readers, and repeated failures are locked out for a minute.</td>
    <td>Below 768 px the sidebar becomes a bottom bar.</td>
  </tr>
</table>

## Roadmap

Each phase gets its own spec and plan before any code is written, in
[`docs/superpowers/`](docs/superpowers/). The full design is in [`docs/architecture/`](docs/architecture/README.md).

| Phase | What you get | Status |
| --- | --- | --- |
| 1a | Foundation: monorepo, login, app shell, database, CI, releases | ✅ v0.2.0 |
| 1b | **Ask** privately: chat answered by a local model (Ollama), with sources shown first; settings | ✅ Done |
| 2a | **Sources**: durable Obsidian ingestion (watcher, reconcile, bge-m3 embeddings), with its state on the Sources screen | ✅ Done |
| 2b | **Search**, chat retrieval and quick capture: hybrid full-text and vector search, your notes in private chat, a capture box | Planned |
| 3 | Embedding evaluation: bge-m3 against MiniLM/e5 on a Polish/English retrieval set; a new space only if it wins | Planned |
| 4 | **Digest** and **Review**: nightly consolidation links notes to projects, people and machines; a morning digest; a review queue | Planned |
| 5 | **Nodes**: see and wake your machines (RTX workstation, MacBook, Proxmox) with truthful online, offline and unknown states | Planned |
| 6 | Paperwork and history: invoices and contracts from PDF, email archives, git history | Planned |
| 7 | Salience: old ideas are surfaced again when they relate to what you're working on, and nothing fades away without your consent | Planned |
| 8 | **Projects** and MCP: pick a project back up with its full context, and let AI tools use what you marked shareable | Planned |

## Requirements

| | Windows | macOS (Apple Silicon) | Linux |
| --- | --- | --- | --- |
| uv, just | `winget install astral-sh.uv Casey.Just` | `brew install uv just` | official install scripts or distro packages |
| Node 24 | `winget install OpenJS.NodeJS.LTS` (or fnm) | `brew install fnm && fnm install` (reads `.nvmrc`) | fnm / nvm |
| pnpm | `corepack enable` | `corepack enable` | `corepack enable` |
| Docker | Docker Desktop | Docker Desktop or OrbStack | Docker Engine |

uv installs Python 3.12 itself, so you don't need to. dbmate (migrations), tsx and the other tools
come with the pnpm workspace.

**Main dependencies:**
- **Backend:** FastAPI, uvicorn, psycopg 3 (async pool), pydantic-settings, argon2-cffi, Typer.
- **Web:** React 19, TypeScript 5.9 (strict), Vite 8, TanStack Router and Query, Tailwind CSS 4,
  Radix/shadcn primitives, openapi-fetch.
- **Quality tools:** ruff, pyright, pytest, Biome, Vitest, Playwright.
- **Database:** PostgreSQL 17 with pgvector.

## Quick start

```bash
git clone https://github.com/mdyzma/ai-second-brain.git
cd ai-second-brain
just setup          # dependencies, .env, the Postgres container and migrations (Docker must be running)
just hash-password  # prints SB_OWNER_PASSWORD_HASH='...'; paste it into .env, keeping the quotes
just dev            # API and web app together
```

Open <http://localhost:5173> and sign in with the password you just hashed. Run every `just`
command from the repository root.

## Everyday commands

| Command | What it does |
| --- | --- |
| `just dev` | API (auto-reload), web app (Vite) and the ingestion worker together, with the database started first |
| `just worker` | The ingestion worker alone (watches the vault, indexes and embeds) |
| `just vault-scan` | One reconcile pass now; add `--allow-mass-delete` to override the mass-deletion guard |
| `just vault-status` | Print the ingestion summary (notes, embedding progress, last scan) as text |
| `just check` | Lint, format check, type checks, token contrast, hard-coded colours, API-client and schema freshness: the same as CI |
| `just test` | Backend (unit and integration), web and helper-script tests |
| `just test-unit` | Only the tests that need no database |
| `just e2e` | Playwright browser tests against a separate test database and ports (8001/5174) |
| `just fmt` | Format and auto-fix everything |
| `just api-client` | Regenerate the TypeScript API client after changing API models |
| `just db::new <name>`, then `just db::migrate` and `just db::dump` | Add a migration and refresh `db/schema.sql` |
| `just db::up` / `just db::down` / `just db::status` | Start or stop the database container, or list migrations |
| `just hash-password` | Hash a new owner password |
| `just chat-smoke` | Ask your configured local model one question (nothing is saved) |
| `just release-dry-run` | Preview the next release version (needs `GITHUB_TOKEN`) |
| `just --list` | Everything else |

## Repository layout

```text
ai-second-brain/
├── backend/                    Python API and admin CLI (uv project, package ai_second_brain)
│   ├── src/ai_second_brain/
│   │   ├── config.py           Settings from .env (pydantic-settings), password-hash validation
│   │   ├── db.py               Async PostgreSQL connection pool (psycopg 3)
│   │   ├── runtime.py          Event loop that psycopg needs on Windows
│   │   ├── auth/               Password hashing, login throttle, server-side sessions
│   │   ├── chat/               Private/cloud routing, Ollama and Anthropic clients, conversations
│   │   ├── vault/              Reading the vault: observe, parse, chunk, watcher, reconcile, moves and deletions
│   │   ├── knowledge/          Sources, revisions, chunks and embeddings in Postgres; the index and embed jobs and the status summary
│   │   ├── ingest/             The worker process (procrastinate queues, watcher, scheduled reconcile)
│   │   └── interfaces/
│   │       ├── api/            FastAPI app, routes (health, auth), cross-site check, API schemas
│   │       └── cli/            `ai-second-brain serve | openapi | hash-password`
│   └── tests/                  unit/ (no database) and integration/ (real Postgres)
├── web/                        React + TypeScript single-page app (pnpm, Vite)
│   ├── src/
│   │   ├── api/                Generated OpenAPI schema and client (never edited by hand)
│   │   ├── design-system/      tokens.css (colours, fonts, radii), theme, UI primitives, app shell
│   │   ├── features/           auth (session, login form, route guard), chat (Ask screen), sources (Sources screen) and screens (placeholders)
│   │   └── routes/             File-based routes: /login and the protected app screens
│   ├── scripts/                Contrast checker and hard-coded-colour guard for the design tokens
│   └── tests/e2e/              Playwright browser tests
├── db/
│   ├── migrations/             dbmate SQL migrations (the source of truth for the schema)
│   └── schema.sql              Generated schema snapshot; CI checks it is current
├── infra/compose.yaml          PostgreSQL 17 + pgvector for development (127.0.0.1:5433)
├── scripts/                    Cross-platform helper scripts (TypeScript run with tsx): database
│                               start-up, schema check, .env set-up, version bump, commit-message check
├── .githooks/commit-msg        Rejects commit messages that aren't Conventional Commits or carry AI attribution
├── .github/workflows/ci.yml    CI (Linux full suite, macOS checks) and the release job
├── .releaserc.json             semantic-release configuration
├── justfile                    The command runner for everything (modules: backend, web, db)
└── docs/
    ├── architecture/           System design, ADRs, stack evaluation, design system, product ideas
    ├── superpowers/            Specs and implementation plans for each phase
    └── images/readme/          The screenshots on this page
```

## How it works

```text
Browser ──HTTP (localhost)──▶ Web app (React SPA) ──/api──▶ FastAPI ──▶ PostgreSQL 17 + pgvector
                                                  │
                                                  ├─ local models (Ollama on your LAN) for private chats
                                                  └─ a cloud model (Anthropic) only for cloud chats you start
```

- **Plain HTTP for now.** Phase 1a runs on localhost over HTTP; TLS comes with deployment.
- **One backend, one datastore.** A modular Python monolith. PostgreSQL holds relational data,
  vectors, jobs and sessions; there is no Redis and no separate vector or graph database
  ([why](docs/architecture/adr/0002-postgres-single-datastore.md)).
- **Private by default.** Each conversation is private (local model) or cloud, chosen when it is
  created and fixed afterwards. Private conversations only reach the Ollama endpoints you configure;
  cloud conversations never include your notes ([design](docs/architecture/system-design.md#5-privacy-architecture)).
- **The API contract drives the UI.** Pydantic models produce the OpenAPI schema, which produces
  the TypeScript types. A change on one side that isn't regenerated fails the check.
- **Endpoints today:** `GET /api/health`, `GET /api/health/ready`, `POST /api/auth/login`,
  `POST /api/auth/logout`, `GET /api/auth/me`, `GET /api/chat/status` and the conversation
  endpoints under `/api/sessions` (answers stream as server-sent events). Errors are always `{"detail": "<code>"}`, where
  `<code>` is a snake_case error name.

## Configuration

`just setup` creates `.env` from `.env.example`. The main settings:

| Variable | Default | Meaning |
| --- | --- | --- |
| `DATABASE_URL` / `TEST_DATABASE_URL` | `postgres://brain:brain@127.0.0.1:5433/…` | Dev and test databases (the Docker container) |
| `SB_OWNER_PASSWORD_HASH` | empty | Owner password hash from `just hash-password`, **in single quotes** |
| `SB_SESSION_TTL_DAYS` | `14` | Session lifetime, extended while you use the app |
| `SB_COOKIE_SECURE` | `false` | Set to `true` behind HTTPS |
| `SB_ALLOWED_ORIGINS` | `http://localhost:5173` | Origins allowed to make changes (the cross-site check) |
| `SB_API_PORT` / `SB_WEB_PORT` | `8000` / `5173` | Development ports |
| `SB_ENV` | `dev` | `dev` enables the API docs at `/api/docs`; `prod` hides them |

### Local models (Ollama)

1. Install Ollama on each host and run `ollama pull <model>` yourself; the app never downloads models.
2. On LAN hosts set `OLLAMA_HOST=0.0.0.0:11434` and keep port 11434 off the internet.
3. Set `SB_OLLAMA_ENDPOINTS` in order of preference (copy the example from `.env.example`), marking
   CPU-only hosts `"degraded": true`.
4. Run `just chat-smoke`.
5. Optionally set `SB_ANTHROPIC_API_KEY` to allow cloud sessions.

The app enforces routing, not the physical location of a URL: a "local" endpoint is whatever you configure.

| Variable | Default | Meaning |
| --- | --- | --- |
| `SB_OLLAMA_ENDPOINTS` | empty | JSON list of `{label, url, model, degraded?}`; the order is the preference |
| `SB_ANTHROPIC_API_KEY` | empty | Empty disables cloud sessions |
| `SB_ANTHROPIC_MODEL` | `claude-sonnet-5-5` | Model for cloud sessions |
| `SB_ANTHROPIC_BASE_URL` | `https://api.anthropic.com` | Pinned; `ANTHROPIC_BASE_URL` is ignored. Tests only |
| `SB_CHAT_MAX_TOKENS` | `2048` | Maximum answer length |
| `SB_CHAT_STATUS_TTL_SECONDS` | `10` | How long the endpoint status is cached |

### Vault ingestion

The worker indexes the Markdown notes of an Obsidian vault. It only reads the vault and never writes to it.
Details are in the [Phase 2a spec](docs/superpowers/specs/2026-09-30-phase-2a-vault-ingestion-design.md).

1. Set `SB_VAULT_PATH` (an absolute path) and, if needed, `SB_VAULT_EXCLUDE` in `.env`.
2. On the embedding host run `ollama pull bge-m3`. Set `SB_EMBED_URL` if embedding runs on a different host from chat.
3. Run `just db::migrate`, then `just dev`. The worker starts and scans the vault.
4. Watch progress on the Sources screen (its **Scan now** button queues a scan), or with `just vault-status`.
5. Network shares and WSL paths may not deliver file events. Rely on the scheduled reconcile and consider lowering `SB_RECONCILE_MINUTES`.

| Variable | Default | Meaning |
| --- | --- | --- |
| `SB_VAULT_PATH` | empty | Absolute path of the vault. Empty disables ingestion (the worker idles and Sources says so) |
| `SB_VAULT_EXCLUDE` | `.obsidian/**,.trash/**,**/.git/**` | Comma-separated globs matched against vault-relative paths. Only `*.md` files are read |
| `SB_EMBED_URL` | empty | Ollama URL for embeddings. Empty uses the first `SB_OLLAMA_ENDPOINTS` URL; with neither, notes are indexed for full text only |
| `SB_EMBED_MODEL` | `bge-m3` | The exact Ollama tag installed on the embedding host, for example `bge-m3` or `bge-m3:567m` |
| `SB_EMBED_BATCH` | `16` | Chunks per embedding call (1 to 128) |
| `SB_RECONCILE_MINUTES` | `15` | Interval of the scheduled reconcile (1 to 1440) |
| `SB_MAX_NOTE_BYTES` | `2000000` | Larger files are not read |

- **Embedding model.** `SB_EMBED_MODEL` must be a tag of the default embedding space's model (`bge-m3`), or the
  worker refuses to start. Models ending in `:cloud` or `-cloud` are refused for embeddings and chat, because
  private text never leaves your LAN. On Windows, prefer `http://127.0.0.1:11434` over `localhost`.
- **What the worker watches.** It watches the vault for changes. A folder rename or move triggers an immediate
  rescan, and a reconcile also runs every `SB_RECONCILE_MINUTES`, so offline edits are picked up.
- **Mass-deletion guard.** If a reconcile finds more than 10 notes missing **and** more than 20% of the live
  notes, it deletes nothing and reports `guard_tripped` (an unmounted drive or a wrong path looks just like that).
  The Sources screen cannot override it; only `just vault-scan --allow-mass-delete` can.
- **One worker per deployment.** A second worker is safe but wasteful, so run just one.

`.env` is never committed. `.env.test` is committed on purpose and contains only test values
(the e2e password is `e2e-test-password`).

## Commit messages and releases

**Commit messages** follow Conventional Commits:
- The header is `type(scope): summary`: imperative, no more than 50 characters (72 is the hard limit), with no period.
- An optional body explains what and why, wrapped at 72 characters.
- The optional footer holds `BREAKING CHANGE:` or `Closes #n`.
- AI attribution (`Co-Authored-By`, "Generated with Claude") is never allowed.

The `commit-msg` hook in `.githooks/` enforces these rules. `just install` enables it (`just hooks` on its own).

**Releases** follow SemVer and are fully automated. After CI passes on `main`, semantic-release reads
the commits since the last `v*` tag. `feat` bumps MINOR, `fix` or `perf` bumps PATCH, and
`BREAKING CHANGE:` or `type!:` bumps MAJOR; other types alone don't release. It then updates the
version files, commits `chore(release): vX.Y.Z [skip ci]`, tags `vX.Y.Z` and publishes a
[GitHub Release](https://github.com/mdyzma/ai-second-brain/releases) with generated notes.
- Never create, move or delete `v*` tags by hand. Fix problems with a new release instead.
- Recommended: protect `v*` tags in GitHub (Settings → Rules → Rulesets → Tag rules).
- To preview locally, set `GITHUB_TOKEN` (e.g. `$env:GITHUB_TOKEN = gh auth token` in PowerShell), then run `just release-dry-run`.

## Troubleshooting

- **`just dev` stops with "run `just hash-password`":** the owner password isn't set yet. Run
  `just hash-password` and paste the printed line into `.env`.
- **Login silently returns to `/login`:** with `SB_COOKIE_SECURE=true` over plain http the browser
  drops the session cookie. Keep it `false` for local http and use `true` only behind HTTPS.
- **The hash is set but login fails:** keep the single quotes around `SB_OWNER_PASSWORD_HASH`.
  Without them, just's `.env` loader expands the `$` characters and breaks the hash.
- **Slow database connections on Windows:** use `127.0.0.1`, not `localhost`. The container
  listens on `127.0.0.1:5433` only, and `localhost` tries IPv6 first.
- **Port 5432 is already in use:** that's fine, because the container uses 5433 so it can run
  next to a locally installed PostgreSQL.
- **"Docker is not reachable":** start Docker Desktop (Windows), Docker Desktop or OrbStack (macOS),
  or the Docker service (Linux).
- **"No local model reachable":** run `just chat-smoke`; every endpoint marked UNREACHABLE failed
  `GET /api/version` within 1 s. Check `OLLAMA_HOST`, the firewall and the URL in `SB_OLLAMA_ENDPOINTS`.
- **"The embedding model isn't installed":** run `ollama pull bge-m3` on the embedding host (use the same tag
  as `SB_EMBED_MODEL`). Embedding resumes by itself; notes are searchable by full text meanwhile.
- **Sources says "found N notes missing and deleted nothing":** the mass-deletion guard tripped. Check
  `SB_VAULT_PATH` (and that the drive is mounted). If the notes really are gone, run
  `just vault-scan --allow-mass-delete`.
- **Sources says "The worker hasn't picked this up yet.":** **Scan now** waits up to 60 s for the worker. Start
  it with `just dev` or `just worker`.
- **The worker exits at start naming two models:** `SB_EMBED_MODEL` isn't a tag of the default space's model
  (`bge-m3`), or ends in `:cloud` or `-cloud`.
- **The dbmate binary can't be downloaded (proxy or offline):** install dbmate with scoop/winget or
  `brew install dbmate`, and set `DBMATE=dbmate` in `.env`.

## Documentation

- [Architecture overview](docs/architecture/README.md): the design, principles and the decisions at a glance
- [System design](docs/architecture/system-design.md): requirements, data model, flows, privacy, deployment and phases
- [Tech stack evaluation](docs/architecture/tech-stack-evaluation.md), including why the backend is Python and the UI is TypeScript
- [Architecture decision records](docs/architecture/adr/)
- [Design system](docs/architecture/design-system-audit.md): tokens, components and the accessibility bar
- [Phase 2a spec (vault ingestion)](docs/superpowers/specs/2026-09-30-phase-2a-vault-ingestion-design.md)
- [Phase 1a spec](docs/superpowers/specs/2026-09-29-phase-1a-foundation-design.md) and
  [implementation plan](docs/superpowers/plans/2026-09-29-phase-1a-foundation.md)

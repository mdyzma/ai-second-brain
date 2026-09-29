# Tech stack evaluation

Date: 2026-09-29. This evaluates every technology named in [`second-brain-prompt.md`](../second-brain-prompt.md), plus the owner's fixed choices (**uv, just, Node + React, PostgreSQL**), against the requirements in [system-design.md](system-design.md#1-requirements). The MVP code is discarded, so nothing is kept only because it exists.

Verdicts: **Adopt** (use now), **Adopt later** (right tool, later phase), **Replace** (the need is real, but use a different tool), **Reject** (the need isn't real, or it conflicts with constraints).

## 1. TypeScript evaluation

TypeScript is certain for the UI. The open question is how far it should reach. Full analysis: [ADR-0011](adr/0011-backend-language-python-vs-typescript.md).

| Where | Verdict | Reasoning |
|---|---|---|
| Web UI (React) | **Adopt, strict mode** | Typed routes, typed API client, discriminated unions for SSE events and node/ingestion/salience states. Plain JavaScript gives up the contract safety that makes a two-language stack safe |
| API contract | **Adopt (generated)** | Pydantic → OpenAPI → `openapi-typescript` → `openapi-fetch`. Types are shared through codegen; CI fails on drift |
| Backend (API, worker, ingestion) | **Evaluated, not chosen (for now)** | Node would give one language, shared Zod schemas, graphile-worker/pg-boss and the reference MCP SDK. It loses on layout-aware PDF/invoice extraction (pdfplumber, OCR, docling) and retrieval-evaluation tooling, which are the two riskiest parts of the product |
| MCP server | Python (same services) | The TS SDK is the reference implementation, but a separate TS MCP server would duplicate backend logic |
| Hybrid (TS API + Python extraction worker) | **Reject for solo dev** | Splits domain logic and the data layer across two languages; the queue must become language-neutral |

**What would flip the backend to TypeScript:** Phase 0 plus the PDF spike showing that extraction can be done by a local vision model through Ollama and that evaluation needs are light. The design keeps that door open. Embeddings go through Ollama over HTTP, the schema lives in language-neutral dbmate SQL, and the queue lives in Postgres.

## 2. Summary by layer

| Layer | Prompt | Verdict | Recommendation | ADR |
|---|---|---|---|---|
| Repo & orchestration | — | Adopt | Monorepo `backend/`, `web/`, `db/`, `infra/`; **just** as the only entry point | [0009](adr/0009-monorepo-toolchain.md) |
| Python tooling | `requirements.txt` | Replace | **uv** (Python 3.12, `uv.lock`), ruff, pyright, pytest | 0009 |
| Node tooling | — | Adopt | **pnpm**, Node LTS pinned; build-time only in prod | 0009, [0010](adr/0010-web-ui-stack.md) |
| Web UI | — (dashboard mentioned) | Adopt | **React 19 + TypeScript + Vite SPA**, TanStack Router/Query, Tailwind v4 + shadcn/ui, Biome, Vitest, Playwright | 0010 |
| SSR framework | — | Reject | Next.js/Remix: a server runtime with no benefit for a single-user LAN app | 0010 |
| Backend architecture | New `app/` tree | Adopt (reshaped) | Modular monolith in `backend/src/second_brain` | [0001](adr/0001-modular-monolith.md) |
| Backend language | Python 3.11+ | Adopt | Python 3.12 (see §1) | [0011](adr/0011-backend-language-python-vs-typescript.md) |
| API | FastAPI | **Adopt now** | Primary interface; SSE for chat; OpenAPI drives the TS client | 0010 |
| Auth / edge | — | Add | Caddy (LAN TLS, static assets, proxy) + single-user session cookie | — |
| Database | PostgreSQL 16 | Adopt (pin 17) | PostgreSQL **17** everywhere; primary storage for everything | [0002](adr/0002-postgres-single-datastore.md) |
| Vectors | pgvector, HNSW, `vector(1536/1024)` | Adopt | pgvector ≥ 0.8, `halfvec`, per-space expression indexes, iterative scans | [0006](adr/0006-embedding-spaces.md) |
| Docker image | `ankane/pgvector:v0.5.1` | Replace | `pgvector/pgvector:pg17`; v0.5.1 predates halfvec and iterative scans | 0002 |
| Full-text | — (missing) | Add | Postgres `tsvector` (`simple`) + RRF fusion | — |
| Graph | (GraphRAG / Neo4j inspiration) | Reject | Entities + edges tables + recursive CTEs; Apache AGE if ever needed | 0002 |
| ORM / driver | SQLAlchemy 2.0 + asyncpg | Replace | **psycopg 3** (async pool) + SQL repositories | [0004](adr/0004-data-access-and-migrations.md) |
| Migrations | Docker init script | Replace | **dbmate** (language-neutral SQL, run via just) | 0004 |
| Queue / scheduler | Celery + Redis | Replace | **procrastinate** (Postgres-backed, periodic tasks) | [0003](adr/0003-postgres-job-queue.md) |
| Cache / STM | Redis | Reject | Durable staging in Postgres; sessions in Postgres; TanStack Query caches on the client | 0002 |
| SSH | Paramiko **and** AsyncSSH | Replace | **asyncssh only** + command catalog | [0008](adr/0008-hardware-execution.md) |
| WoL | wakeonlan | Adopt | From the Proxmox worker on the same L2 | 0008 |
| Hypervisor | proxmoxer | Adopt later | API token, read-only role | 0008 |
| PDF | pdfplumber | Adopt | Plus an explicit "OCR needed" state; `ocrmypdf` for scans; compare with an Ollama vision model in the spike | 0011 |
| Email | ".eml/.mbox parser" | Adopt | Python stdlib `email` + `mailbox` | — |
| Notes | Obsidian watcher, Trilium API | Adopt | `watchdog` + nightly reconcile; Trilium ETAPI later | — |
| Local LLM | Ollama (or vLLM) in a Proxmox LXC | Adopt Ollama | Workstation GPU on demand + Proxmox CPU fallback; vLLM rejected (no multi-user throughput need) | [0005](adr/0005-local-inference-topology.md) |
| Embeddings | bge-m3 | Adopt | Via Ollama `/api/embed`; confirm with a bake-off | 0006 |
| Cloud LLM | Claude 3.5 Sonnet / Gemini | Replace | Anthropic only, model id from config (current generation, e.g. `claude-sonnet-5-5`); one cloud provider keeps the egress surface small | — |
| OpenAI SDK | `openai>=1.14` | Reject | Not needed; cloud embeddings are forbidden | 0006 |
| MCP | server + host, "root administrator" | Adopt later (server only) | Thin adapter, shareable-only default, read-only tools | [0007](adr/0007-mcp-as-adapter.md) |
| Boundary checks | — | Add | `import-linter` (Python); Biome import rules (web) | 0001 |

## 3. Runtime footprint

Production processes: PostgreSQL, Caddy, the API (uvicorn), the worker, the sync watcher, and Ollama on 1–2 hosts. **No Node, Redis or Celery at runtime.** Node exists in dev and CI only.

Dependencies not added (compared with the prompt): `sqlalchemy`, `asyncpg`, `celery`, `redis`, `paramiko`, `openai`, and Python `sentence-transformers` in the runtime (it is used in the eval harness only).

## 4. Issues found in the prompt's code samples

These are listed so nobody copies them:

1. `CREATE EXTENSION pgvector`: the extension is named `vector`.
2. Several `CREATE TABLE` statements are stuck to the end of `--` comment lines (`-- 4. Tabela projektówCREATE TABLE projects (`), so they never execute.
3. Decorators are stuck to function definitions in the MCP sample (`@app_mcp_server.list_tools()async def ...`), which is a syntax error.
4. The MCP tool handlers return simulated data (hard-coded VRAM, fake search results).
5. `docker-compose.yml` publishes Postgres and Redis on all interfaces with default passwords, and uses the obsolete `version:` key.
6. `hardware_nodes` defaults `cached_gpu_util` to `0.0` and `is_online` to `false`, so a never-observed node looks "offline and idle" instead of "unknown".
7. `unified_ltm_chunks` uses `ON DELETE CASCADE` from `hardware_nodes`/`financial_records`, so deleting an inventory row would delete memories.
8. The Claude Desktop config example puts the DB password in plain JSON.

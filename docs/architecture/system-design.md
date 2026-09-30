# Second Brain: target system design

Date: 2026-09-29 · Status: **Proposed** · Owner: Michal Dyzma
Inputs: [`docs/second-brain-prompt.md`](../second-brain-prompt.md), [assessment](../superpowers/specs/2026-09-29-second-brain-assessment.md), [private chat routing spec](../superpowers/specs/2026-09-29-private-chat-routing-design.md), repository at `8342184`.

This document answers "what is the right architecture for the vision in the prompt?" It is the **target** the roadmap slices converge on, not a single implementation plan. Each numbered phase in [§9](#9-delivery-phases) still gets its own spec. Decisions are recorded as ADRs in [`adr/`](adr/); the stack verdicts are in [tech-stack-evaluation.md](tech-stack-evaluation.md).

---

## 1. Requirements

### 1.1 Functional

| ID | Requirement | Source in prompt |
|---|---|---|
| F1 | Ask questions over personal knowledge (notes, ADRs, chats, code docs) and get source-cited answers | Omni-search, LTM |
| F2 | Ingest Obsidian vault continuously; Trilium later | Engram ingestion |
| F3 | Ingest git history, PDFs (invoices/contracts) and email archives with structured extraction | Ingestion pipelines |
| F4 | Maintain a knowledge graph: projects, skills (tree), counterparties, hardware, and links from chunks to them | LTM schema |
| F5 | Nightly consolidation: link new material to entities, embed, promote to searchable | Sleep cycle |
| F6 | Salience: stale material (superseded, expired) ranks lower, while one-off ideas stay findable and are resurfaced by association; only the user archives | Synaptic plasticity / limbo |
| F7 | Observe LAN hardware (Proxmox, RTX 5090 workstation, MacBook M1), wake nodes, run allowlisted diagnostics | Hardware orchestration |
| F8 | Compound requests combining hardware state and memory search, with separate outcomes | Omni-search router |
| F9 | Expose the same capabilities to external AI clients through MCP | MCP section |

### 1.2 Non-functional

| Concern | Target (proposed, single user) | Rationale |
|---|---|---|
| Privacy | **Zero** private-classified content in any cloud payload, enforced in one gateway and tested by observing egress | Hard constraint in prompt |
| Durability | An acknowledged import is never lost; a failed re-index never removes the previous searchable version | Assessment gap #5 |
| Retrieval latency | p95 < 400 ms for hybrid search over ≤ 1 M chunks (excl. generation) | Interactive chat |
| Private generation | First token < 5 s on the chosen local host; measured, not assumed | Riskiest assumption |
| Availability | Best-effort home-lab; degrade gracefully when the GPU host sleeps | Nodes power-cycle |
| Operability | One person can run it: ≤ 4 long-running processes, one datastore, backups via `pg_dump` | Solo operator |
| Traceability | Every answer lists deterministic sources; every action has a receipt with timestamp and outcome | Trust |
| Language | Polish and English content and queries | Notes are bilingual |

### 1.3 Constraints and assumptions

- One trusted user, one trusted flat L2 LAN (`192.168.88.0/24`). No multi-tenancy.
- **Greenfield.** The Phase 1 MVP (`src/ai_second_brain`, Poetry, Click CLI) was a first attempt and is discarded. It is not a constraint or a template. Its only reusable asset is the Obsidian vault it indexed, which is re-ingested from source.
- **Toolchain (owner decision):** **uv** manages Python versions and dependencies; **just** is the single command runner across the whole stack (Python, Node, database, infra); **Node + React** is the primary UI; **PostgreSQL** is the primary storage. See [ADR-0009](adr/0009-monorepo-toolchain.md) and [ADR-0010](adr/0010-web-ui-stack.md).
- Proxmox host has no GPU (assumption — verify). The RTX 5090 workstation is the only strong inference host and is **not always on**.
- PostgreSQL version is inconsistent across docs (16 / 17 / 18). Compose uses 17; production is unverified. Pin one in [ADR-0002](adr/0002-postgres-single-datastore.md).

### 1.4 Load estimate

| Source | Assumed volume | Chunks (≈) |
|---|---|---|
| Obsidian + Trilium | 5 000 notes | 50 k |
| Email archive | 50 000 messages | 250 k |
| PDFs (invoices/contracts) | 2 000 docs | 20 k |
| Git history (commits + docs) | 30 repos | 60 k |
| Chat transcripts | 3 years | 50 k |
| **Total** | | **~430 k** |

At 1024-d `halfvec` (2 B/dim) vectors are ~0.9 GB, HNSW roughly 2× that, text + metadata a few GB. A single PostgreSQL instance with 8–16 GB RAM handles this comfortably. **Nothing in this system needs horizontal scaling**; the design optimizes for correctness, privacy and operability instead.

---

## 2. Architecture style

**Monorepo with two apps: a Python modular-monolith backend and a React SPA, plus one datastore.** The backend is one Python package split into bounded modules with explicit interfaces. The same code runs as several processes (API, worker, MCP server, admin CLI). The web UI talks to the backend only through a typed HTTP API (OpenAPI → generated TypeScript client) and SSE streams. PostgreSQL is the only stateful dependency: it stores knowledge, vectors, jobs, sessions and hardware observations.

Rejected alternatives (see [ADR-0001](adr/0001-modular-monolith.md)): microservices (operational cost with no scale driver), and Celery + Redis (extra moving parts; Postgres covers queueing at this scale). A Node backend (BFF) was also rejected: the ML/embedding/SSH ecosystem is in Python, and Node is needed only to build the UI ([ADR-0010](adr/0010-web-ui-stack.md)).

```
   ┌──────────────── Browser (LAN devices) ────────────────┐
   │  React SPA: chat · search · resume · digest · review   │
   │  queue · nodes · sources/sharing · settings            │
   └───────────────┬────────────────────────────────────────┘
                   │ HTTPS (Caddy)  /api/* JSON + SSE   /* static assets
                         ┌────────────────── Interfaces ──────────────────┐
                         │  HTTP API (FastAPI, primary)  · SSE streams     │
                         │  MCP server (stdio, later) · admin CLI (Typer)  │
                         └───────────────┬─────────────────────────────────┘
                                         │ application services (sync + async facades)
   ┌─────────────────────────────────────┼──────────────────────────────────────────┐
   │                                     ▼                                          │
   │  ┌──────────────┐   ┌──────────────────────┐   ┌──────────────────────────┐    │
   │  │ conversation │──▶│ search (hybrid RAG)  │──▶│ llm gateway (privacy     │──┐ │
   │  │ sessions/STM │   │ vector + FTS + graph │   │ policy, routing, egress) │  │ │
   │  └──────────────┘   └──────────┬───────────┘   └──────────────────────────┘  │ │
   │                                │                                             │ │
   │  ┌──────────────┐   ┌──────────▼───────────┐   ┌──────────────────────────┐  │ │
   │  │ sources /    │──▶│ knowledge (LTM):     │◀──│ lifecycle: consolidation │  │ │
   │  │ ingestion    │   │ entities, chunks,    │   │ ("sleep"), salience,     │  │ │
   │  │ adapters     │   │ embeddings, edges    │   │ dormancy                 │  │ │
   │  └──────────────┘   └──────────────────────┘   └──────────────────────────┘  │ │
   │                                                                              │ │
   │  ┌───────────────────────────────┐   ┌──────────────────────────────────┐    │ │
   │  │ hardware: inventory, observe, │   │ jobs: Postgres-backed queue +    │    │ │
   │  │ wake, allowlisted commands    │   │ periodic schedule (procrastinate)│    │ │
   │  └───────────────────────────────┘   └──────────────────────────────────┘    │ │
   └──────────────────────────────────────────────────────────────────────────────┘ │
                 │                         │                                         │
                 ▼                         ▼                                         ▼
      PostgreSQL + pgvector       LAN nodes (SSH / WoL /            Ollama (LAN)  │  Anthropic API
      (single source of truth)    Proxmox API)                      private tier  │  cloud tier
```

### 2.1 Module boundaries

| Module | Owns | Must not |
|---|---|---|
| `sources` | Adapters (Obsidian, Trilium, git, PDF, email), source identity, revisions, raw artifacts | Call LLMs directly; write chunks (it emits revisions) |
| `knowledge` | Schema, repositories, chunking, embedding, entity/edge storage | Know about CLI/HTTP; decide privacy |
| `lifecycle` | Consolidation jobs, entity extraction, salience scoring, dormancy transitions | Delete data |
| `search` | Hybrid retrieval, filters, re-ranking, source formatting | Send anything off-box |
| `llm` | Provider adapters, **privacy policy enforcement**, prompt assembly limits | Be bypassed: it is the only module that imports provider SDKs |
| `conversation` | Sessions, bounded history, turn records | Persist cloud-mode content alongside private evidence |
| `hardware` | Node inventory, observations, WoL, command catalog, Proxmox client | Execute free-form commands |
| `jobs` | Queue, schedules, retries | Contain domain logic |
| `interfaces` | HTTP API (routers, auth, SSE), MCP, admin CLI: parse, authorize, serialize | Contain domain logic |

An import-linter contract (`import-linter` in CI) enforces that only `llm` imports `anthropic`/`httpx` provider calls and only `hardware` imports `asyncssh`/`wakeonlan`/`proxmoxer`.

### 2.2 Repository layout

```
ai-second-brain/
├── justfile                  # the one entry point: just setup | dev | check | test | db-* | build | deploy
├── backend/                  # uv project (pyproject.toml + uv.lock), Python 3.12
│   ├── src/ai_second_brain/
│   │   ├── sources/ knowledge/ lifecycle/ search/ llm/ conversation/ hardware/ jobs/
│   │   └── interfaces/
│   │       ├── api/          # FastAPI app, routers, schemas (Pydantic = API contract)
│   │       ├── mcp/          # MCP server (phase 8)
│   │       └── cli/          # admin CLI: migrate, doctor, reindex, import
│   └── tests/                # unit + integration (real Postgres)
├── web/                      # pnpm project: Vite + React + TypeScript
│   ├── src/
│   │   ├── api/              # generated from backend OpenAPI (never hand-edited)
│   │   ├── design-system/    # tokens.css, primitives (shadcn/ui), domain components
│   │   ├── features/         # chat, search, resume, digest, review, nodes, sources, settings
│   │   └── routes/           # TanStack Router file routes
│   └── tests/                # Vitest + Playwright
├── db/
│   ├── migrations/           # dbmate SQL migrations (source of truth for schema)
│   └── seeds/                # dev fixtures (synthetic, never real private data)
├── infra/
│   ├── compose.yaml          # dev: postgres(pgvector) + optional ollama
│   ├── caddy/Caddyfile       # prod: TLS on LAN, /api → uvicorn, / → web/dist
│   └── systemd/              # api, worker, sync units for Proxmox LXCs
└── docs/
```

**API contract flow:** Pydantic models in `interfaces/api` → FastAPI OpenAPI JSON → `just api-client` runs `openapi-typescript` into `web/src/api/` → typed `openapi-fetch` calls + TanStack Query hooks. CI fails if the generated client is stale (`just api-client && git diff --exit-code`).

### 2.3 API surface (v1, abridged)

| Method & path | Purpose | Notes |
|---|---|---|
| `POST /api/sessions` | Create chat session `{mode: private\|cloud}` | Mode immutable per session |
| `POST /api/sessions/{id}/turns` | Ask; response is **SSE**: `status`, `sources`, `token`, `receipt`, `done`, `error` events | Sources sent before tokens, so the UI shows evidence first |
| `GET /api/search?q=&kinds=&tiers=&entity=` | Hybrid search, no generation | Retrieval-first mode |
| `GET /api/projects/{id}/resume` | Resume page: decisions, commits, TODOs, emails, environment, node state | North-star feature |
| `GET /api/digest/{date}` | Morning digest | |
| `GET/POST /api/review/edges` | Accept/reject proposed links | |
| `POST /api/sources/{id}/sensitivity`, `/pin`, `/salience` | Share, pin, restore, let fade | Explicit user actions = salience events |
| `GET /api/nodes`, `POST /api/nodes/{id}/wake` | Hardware state; wake needs `confirm: true` | Returns `ActionReceipt` |
| `POST /api/capture` | Quick note into `Inbox/` | Capture from anywhere |
| `GET /api/health`, `/api/doctor` | Liveness; dependency checks | |

Auth: single-user login (argon2 password hash in config, HTTP-only `SameSite=Strict` session cookie), CSRF protection on mutating routes, API bound to localhost behind Caddy, and Caddy reachable only on the LAN. MCP and CLI use a separate API token when they call over HTTP.

---

## 3. Data model (LTM)

Design principles:

1. **Separate identity, revision, chunk and embedding.** A note changes; its identity does not. Embeddings depend on a model; chunks do not.
2. **Two orthogonal state machines.** *Ingestion state* (pending → indexed / failed) is about pipeline progress. *Salience tier* (active / dormant / superseded / archived) is about relevance. The prompt conflates them; the existing `short_term_memory.status` conflates them too.
3. **Typed entities + a generic edge table** give a knowledge graph without a graph database (recursive CTEs cover the skill tree and 2–3 hop traversals).
4. **Sensitivity is data, not a heuristic.** Every source carries a `sensitivity` label, default `private`.

### 3.1 Core tables (abridged DDL, target shape)

```sql
CREATE EXTENSION IF NOT EXISTS vector;          -- extension name is "vector", not "pgvector"

CREATE TYPE sensitivity    AS ENUM ('private', 'shareable');
CREATE TYPE ingest_state   AS ENUM ('pending', 'indexed', 'failed', 'superseded', 'tombstoned');
CREATE TYPE salience_tier  AS ENUM ('active', 'dormant', 'superseded', 'archived');
CREATE TYPE source_kind    AS ENUM ('obsidian', 'trilium', 'git', 'pdf', 'email', 'chat', 'adr', 'manual');

-- Where things come from -------------------------------------------------------------
CREATE TABLE sources (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind          source_kind NOT NULL,
    external_ref  text NOT NULL,                 -- vault-relative path, message-id, repo@sha, file hash
    title         text,
    sensitivity   sensitivity NOT NULL DEFAULT 'private',
    salience      salience_tier NOT NULL DEFAULT 'active',
    pinned        boolean NOT NULL DEFAULT false,  -- pinned sources are never penalized
    retention     text NOT NULL DEFAULT 'default', -- 'legal' => exempt from dormancy (financial)
    current_revision_id uuid,                    -- FK added below; the searchable revision
    created_at    timestamptz NOT NULL DEFAULT now(),
    deleted_at    timestamptz,                   -- tombstone, never hard delete from sync
    UNIQUE (kind, external_ref)
);

CREATE TABLE source_revisions (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id     uuid NOT NULL REFERENCES sources(id),
    content_hash  bytea NOT NULL,                -- sha256 of normalized content: idempotency key
    raw_text      text NOT NULL,
    metadata      jsonb NOT NULL DEFAULT '{}',   -- frontmatter, headers, extraction confidence
    state         ingest_state NOT NULL DEFAULT 'pending',
    error         text,                          -- category only, never content
    observed_at   timestamptz NOT NULL DEFAULT now(),
    indexed_at    timestamptz,
    UNIQUE (source_id, content_hash)
);
ALTER TABLE sources ADD FOREIGN KEY (current_revision_id) REFERENCES source_revisions(id);

-- What we search --------------------------------------------------------------------
CREATE TABLE chunks (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    revision_id   uuid NOT NULL REFERENCES source_revisions(id) ON DELETE CASCADE,
    ordinal       int  NOT NULL,
    heading_path  text[],                        -- e.g. {'Projects','LLM fine-tune'}
    content       text NOT NULL,
    tsv           tsvector GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED,
    UNIQUE (revision_id, ordinal)
);
CREATE INDEX chunks_tsv_gin ON chunks USING gin (tsv);

CREATE TABLE embedding_spaces (                  -- one row per model; never mix spaces
    id            smallint PRIMARY KEY,
    model         text NOT NULL UNIQUE,          -- 'all-MiniLM-L6-v2', 'bge-m3'
    dims          int  NOT NULL,
    is_default    boolean NOT NULL DEFAULT false
);

CREATE TABLE chunk_embeddings (
    chunk_id      uuid NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    space_id      smallint NOT NULL REFERENCES embedding_spaces(id),
    embedding     halfvec NOT NULL,              -- dimension fixed per space via expression index
    PRIMARY KEY (chunk_id, space_id)
);
-- One HNSW index per space, cast to that space's dimension (pgvector expression-index pattern):
-- CREATE INDEX chunk_emb_s2_hnsw ON chunk_embeddings
--   USING hnsw ((embedding::halfvec(1024)) halfvec_cosine_ops) WHERE space_id = 2;

-- The graph -------------------------------------------------------------------------
CREATE TABLE entities (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    type          text NOT NULL CHECK (type IN
                    ('project','skill','person','organization','hardware_node','topic')),
    name          text NOT NULL,
    parent_id     uuid REFERENCES entities(id),  -- skill tree / project hierarchy
    attributes    jsonb NOT NULL DEFAULT '{}',   -- scope: personal|commercial, repo url, ...
    salience      salience_tier NOT NULL DEFAULT 'active',
    UNIQUE (type, name)
);

CREATE TABLE edges (                             -- typed, provenance-carrying relations
    src_type      text NOT NULL,                 -- 'source' | 'chunk' | 'entity'
    src_id        uuid NOT NULL,
    relation      text NOT NULL,                 -- 'mentions','about','runs_on','invoiced_by','uses_skill'
    dst_entity_id uuid NOT NULL REFERENCES entities(id),
    confidence    real NOT NULL DEFAULT 1.0,
    origin        text NOT NULL,                 -- 'user','rule','llm:<model>'
    status        text NOT NULL DEFAULT 'accepted' CHECK (status IN ('proposed','accepted','rejected')),
    created_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (src_type, src_id, relation, dst_entity_id)
);

-- Structured extraction -------------------------------------------------------------
CREATE TABLE financial_records (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id        uuid NOT NULL REFERENCES sources(id),
    record_type      text NOT NULL CHECK (record_type IN ('invoice','contract')),
    counterparty_id  uuid REFERENCES entities(id),
    amount           numeric(14,2),
    currency         char(3),
    tax_id           text,                       -- NIP; validated checksum when PL
    issue_date       date,
    due_date         date,
    expiry_date      date,
    extraction       jsonb NOT NULL,             -- field-level confidence + page/bbox provenance
    verified_by_user boolean NOT NULL DEFAULT false
);

CREATE TABLE emails (
    source_id     uuid PRIMARY KEY REFERENCES sources(id),
    message_id    text UNIQUE,
    thread_key    text,
    from_addr     text, to_addrs text[], subject text,
    sent_at       timestamptz
);
```

Hardware, salience, jobs and conversation tables are in their own sections below.

### 3.2 Why not the prompt's `unified_ltm_chunks`

The prompt puts content, one vector, status, counters and three nullable FKs (`project_id`, `hardware_id`, `financial_id`) in one row. That breaks down on: (a) a chunk related to two projects, (b) changing the embedding model (every row rewritten, index rebuilt, mixed dims), (c) re-indexing a note atomically, (d) counting salience on every retrieval (write amplification on the hottest table). The split above fixes each while keeping one-query hybrid search.

### 3.3 Starting from scratch (no V1 migration)

The V1 tables (`agent_memories`, `short_term_memory`) are not migrated. Their content was derived from the Obsidian vault, so the new ingestion pipeline re-creates it with proper source identity, revisions and the chosen embedding model. Steps: create a fresh database `ai_second_brain` with dbmate migrations → run the initial vault scan → verify counts in `doctor` → drop the old database once satisfied. Schema changes from here on go only through `db/migrations/` ([ADR-0004](adr/0004-data-access-and-migrations.md)).

---

## 4. Key flows

### 4.1 Ingestion (durable, replaces "engram STM buffer")

```
file event / scan / import
        │
        ▼
 sources adapter ── normalize ── sha256 ──▶ upsert source + INSERT revision (state=pending)
        │                                         │   (idempotent: UNIQUE(source_id, hash))
        │                                         ▼
        │                              enqueue job  index_revision(rev_id)
        ▼                                         │
 periodic reconcile (full scan diff)              ▼
  → detects missed events, deletes    worker: chunk → embed (local) → write chunks/embeddings
    (tombstone), moves (same hash)            │  in ONE transaction:
                                              │    new revision → indexed
                                              │    previous revision → superseded
                                              │    sources.current_revision_id = new
                                              ▼
                                   searchable immediately (fast path)
                                   entity linking waits for sleep cycle
```

The "STM buffer" from the prompt is the set of `pending` revisions plus recently indexed revisions that have not been consolidated. It is **durable** — volatile STM is reserved for conversation state and telemetry. New notes are searchable within seconds (embedding is cheap and local); the expensive LLM work (entity extraction, linking, summarization) is what waits for the night.

### 4.2 Sleep cycle (consolidation)

Scheduled at 02:00 via the job scheduler; idempotent per revision.

1. **Wake inference host (optional).** If the GPU workstation is configured as the consolidation host and is asleep, send WoL, wait for `online` with a deadline (e.g. 5 min). If it does not come up, fall back to the Proxmox CPU model or skip and retry next night. This is where hardware orchestration directly serves memory — see [product-brainstorm.md](product-brainstorm.md#idea-3-the-nightly-shift).
2. **Select work:** revisions indexed since last run and not yet consolidated (`metadata->>'consolidated_at' IS NULL`).
3. **Extract** with the local model, per revision, structured JSON: entities mentioned, candidate relations, one-line summary. Validate against a Pydantic schema; invalid output → retry once → mark `consolidation_failed`.
4. **Resolve** entities against existing ones (exact name → alias table → embedding similarity of entity names ≥ threshold). New entities are created as `proposed` unless confidence is high.
5. **Write edges** with `origin='llm:<model>'`, `confidence`, `status='proposed'|'accepted'` by threshold.
6. **Recompute salience** (4.3) and apply tier transitions.
7. **Morning digest:** a short report — new entities, low-confidence links awaiting review, "Rediscover" (at most 1 dormant idea strongly matching yesterday's work; a 3–5 item batch on Sundays), newly superseded items, failures. It is shown as the **Digest** screen in the web UI (the landing page each morning) and can optionally be written as a note into the vault.
8. **Suspend** the GPU host if the system woke it and nobody else is using it (check GPU util + logged-in sessions).

All LLM calls in the sleep cycle go through the `llm` gateway with `sensitivity` of the revision; private revisions can only reach the local tier.

### 4.3 Salience and dormancy

Full rationale is in [ADR-0012](adr/0012-salience-without-popularity-bias.md). A first draft (frequency × decay, with Dormant filtered out of search) was rejected because it rewards whatever is already popular and buries one-off ideas.

- **Relevance dominates.** Salience is a bounded prior: `final = rrf × (1 + prior)`, `prior ∈ [−0.15, +0.15]`. It breaks ties and never overrides a strong match.
- **Prior components:** user interest (user-originated events only, decayed with a 90-day half-life), a **distinctiveness** bonus (unique ideas with no near neighbours are protected), and a **staleness** penalty backed by evidence (superseded, closed, expired).
- **Tiers:** Active · Dormant (computed from inactivity; *still searched*; eligible for resurfacing) · Superseded (evidence-based; linked to its successor; penalized) · Archived (user only; the only tier excluded by default). The Pinned flag and `retention='legal'` are never penalized.
- **Revival by association:** consolidation links new revisions to similar Dormant sources and reports them in the digest. Each result list reserves one "From earlier" slot for the best relevant Dormant item. Rediscover runs on a hybrid cadence: at most 1 association-triggered item per day, plus a Sunday review of 3–5 items (ADR-0012 §4).
- **Signals:** edit, open, click on a cited source, and pin, plus commits/emails linked to an entity. System exposure (a search hit, an uninteracted citation) is **not** counted.
- **Per-kind lifecycles:** ideas, projects (explicit status), financial/legal, email threads, chat transcripts.
- Salience ships only if the eval shows no drop in long-tail recall@10 against a pure-relevance baseline.

```sql
CREATE TABLE salience_events (
    id          bigserial PRIMARY KEY,
    target_type text NOT NULL,       -- 'source' | 'entity'
    target_id   uuid NOT NULL,
    kind        text NOT NULL,       -- 'edited','opened','source_clicked','pinned','feedback_up','feedback_down','linked_commit','linked_email'
    weight      real NOT NULL,
    at          timestamptz NOT NULL DEFAULT now(),
    dedupe_key  text UNIQUE          -- one per target/kind/day/session
);
CREATE TABLE salience_scores (       -- recomputed nightly; not on the hot chunk table
    source_id        uuid PRIMARY KEY REFERENCES sources(id),
    user_interest    real NOT NULL,
    distinctiveness  real NOT NULL,
    staleness        real NOT NULL,
    prior            real NOT NULL,  -- clamped to [-0.15, 0.15]
    computed_at      timestamptz NOT NULL
);
-- sources.salience gains 'superseded'; sources.superseded_by uuid REFERENCES sources(id)
```

User-facing names: **Active / Dormant / Superseded / Archived** (see [design-system-audit.md](design-system-audit.md)). "Limbo" and "synaptic" stay in internal docs.

### 4.4 Chat / omni-search turn

```
input ──▶ interface parses mode + intents
            │
            ├─ hardware intent? (explicit verbs: "wake", "is X on", "status")
            │      └─▶ hardware service ─▶ ActionReceipt{node, action, state, observed_at}
            │
            └─ knowledge intent
                   ├─ retrieve: vector (default space) ∪ FTS (tsv) → RRF fuse → filters
                   │            (salience, kind, entity, date) → optional graph expansion
                   │            (1 hop from matched entities) → top-k
                   ├─ build evidence pack with sensitivity = max(sensitivity of items)
                   └─ llm gateway: route by (session mode, evidence sensitivity) → answer
            │
            ▼
 stream (SSE): status → sources → tokens → receipts → done
 UI renders: mode badge · source list (before the answer) · answer · action receipts (separately)
 record: turn + salience events ('cited_in_answer' for sources shown)
```

Intent detection for hardware is **rule-based and explicit** (UI buttons, slash-commands such as `/wake workstation`, or clear verbs); an LLM may *propose* a hardware action but a state-changing action (wake, suspend) needs explicit user confirmation unless the request itself said so. Compound requests return a composite result where each part has its own status, as the assessment requires.

### 4.5 Hybrid retrieval query (sketch)

```sql
WITH vec AS (
  SELECT c.id, row_number() OVER (ORDER BY e.embedding::halfvec(1024) <=> $1) AS r
  FROM chunk_embeddings e JOIN chunks c ON c.id = e.chunk_id
  JOIN source_revisions rv ON rv.id = c.revision_id
  JOIN sources s ON s.current_revision_id = rv.id
  WHERE e.space_id = $2 AND s.deleted_at IS NULL AND s.salience <> 'archived'
  ORDER BY e.embedding::halfvec(1024) <=> $1 LIMIT 50
), fts AS (
  SELECT c.id, row_number() OVER (ORDER BY ts_rank_cd(c.tsv, q) DESC) AS r
  FROM chunks c
  CROSS JOIN websearch_to_tsquery('simple', $4) AS q
  JOIN source_revisions rv ON rv.id = c.revision_id
  JOIN sources s ON s.current_revision_id = rv.id
  WHERE c.tsv @@ q AND s.deleted_at IS NULL AND s.salience <> 'archived'
  ORDER BY ts_rank_cd(c.tsv, q) DESC LIMIT 50
)
), fused AS (
  SELECT id, sum(1.0 / (60 + r)) AS rrf    -- reciprocal rank fusion, k = 60
  FROM (SELECT * FROM vec UNION ALL SELECT * FROM fts) u
  GROUP BY id
)
SELECT f.id, f.rrf * (1 + coalesce(ss.prior, 0)) AS score   -- bounded salience prior (ADR-0012)
FROM fused f
JOIN chunks c ON c.id = f.id
JOIN source_revisions rv ON rv.id = c.revision_id
LEFT JOIN salience_scores ss ON ss.source_id = rv.source_id
ORDER BY score DESC LIMIT $5;
```

After this query, the application swaps the last result slot for the best Dormant hit above a relevance floor, if the list has none ("From earlier"; ADR-0012 §4).

`'simple'` text search config because PostgreSQL ships no Polish stemmer; FTS catches exact identifiers (NIP numbers, hostnames, error codes) that embeddings miss.

---

## 5. Privacy architecture

The single most important boundary. Builds on the approved [routing spec](../superpowers/specs/2026-09-29-private-chat-routing-design.md) (phase 1) and generalizes it.

### 5.1 Tiers and policy

| Tier | Where | Allowed inputs |
|---|---|---|
| `local` | Ollama on LAN hosts listed in config (Proxmox CPU, workstation GPU, Mac) | Anything |
| `cloud` | Anthropic API | Only `shareable` evidence + text the user typed in a cloud-mode session |

Policy function (one place, pure, exhaustively tested):

```
route(session_mode, evidence) ->
    if session_mode == private: local           # never cloud, no fallback
    if session_mode == cloud:
        if any(item.sensitivity == private for item in evidence): drop those items (report count)
        return cloud
```

- Phase 1: all existing data is `private`, so cloud mode simply has no retrieval (matches the routing spec).
- Later: users can mark whole sources or folders `shareable` (e.g. `vault/Public/`, public repos' ADRs). Classification is **explicit, never inferred**.
- The gateway also scrubs outbound error bodies and never logs payloads.

### 5.2 Egress paths to account for

| Path | Control |
|---|---|
| Chat generation | Gateway policy above |
| Sleep-cycle extraction | Always `local` for private revisions; `shareable` may use cloud if enabled |
| Embeddings | Always local (sentence-transformers / Ollama embeddings); no cloud embedding APIs |
| **MCP tool results** | A cloud-backed MCP client (Claude Code, Claude Desktop) forwards tool output to its provider. So the MCP server treats every caller as **cloud tier** and returns `shareable` content only, unless the operator sets `MCP_ALLOW_PRIVATE=true` with a documented warning. See [ADR-0007](adr/0007-mcp-as-adapter.md). |
| HTTP API / web UI | Behind Caddy on the LAN only, session auth; responses carry private data only to the owner's own browser. The SPA loads no third-party scripts, fonts or analytics (strict CSP, `connect-src 'self'`), so the browser cannot leak it either |
| Logs / traces | Metadata only (mode, component, duration, error category) |
| Backups | Encrypted `pg_dump` (age/gpg) before leaving the Proxmox host |

### 5.3 Where the "local" model runs

The prompt assumes Ollama "inside Proxmox". On a GPU-less host that means a small CPU model (e.g. 7–8 B Q4), which is the riskiest assumption in the whole system. Proposed topology ([ADR-0005](adr/0005-local-inference-topology.md)):

- **Interactive private chat:** Ollama on the workstation when online (fast, large model); otherwise Ollama on Proxmox (small model) with a visible "Private — small local model" label. No cloud fallback, ever.
- **Sleep cycle:** wake the workstation, run batch extraction on the GPU, suspend it.
- **Embeddings:** on the Proxmox worker (CPU is fine for bge-m3 / MiniLM at ingestion rates).

All three hosts are the owner's machines on the trusted LAN, so this stays within "local". The 20-question evaluation from the assessment must be run on **both** local hosts before committing.

---

## 6. Hardware subsystem

### 6.1 State model (truthful states)

```
             WoL sent                probe ok
 unknown ─────────────▶ waking ─────────────────▶ online
    ▲  ▲                  │ deadline passed          │ probe fails ×2
    │  └──── stale ◀──────┘ (→ unknown)              ▼
    │  (observation older than TTL)             unreachable   (≠ powered off)
    └───────────────────────────────────────────────┘
 "suspended" is only reported when the system itself suspended the node and saw it drop.
```

```sql
CREATE TABLE hardware_nodes (             -- inventory (LTM)
    entity_id    uuid PRIMARY KEY REFERENCES entities(id),
    ssh_alias    text NOT NULL,            -- resolved via ~/.ssh/config of the worker user
    mac_address  macaddr,
    wol_broadcast inet,
    capabilities text[] NOT NULL DEFAULT '{}',   -- 'nvidia_smi','powermetrics','proxmox_api','ollama'
    spec         jsonb NOT NULL DEFAULT '{}'     -- GPU, VRAM, CPU, RAM
);
CREATE TABLE node_observations (          -- STM-ish, time-bounded; pruned after 30 days
    id           bigserial PRIMARY KEY,
    node_id      uuid NOT NULL REFERENCES hardware_nodes(entity_id),
    state        text NOT NULL,            -- online|unreachable|waking|unknown
    metrics      jsonb,                    -- gpu_util, vram_used_mb, load1, mem_used
    error        text,                     -- category only
    observed_at  timestamptz NOT NULL DEFAULT now()
);
CREATE VIEW node_latest AS SELECT DISTINCT ON (node_id) * FROM node_observations
  ORDER BY node_id, observed_at DESC;
```

No credentials in the database. SSH keys stay in the worker user's `~/.ssh`, host keys verified against `known_hosts` (no auto-accept). Proxmox uses an API **token** with a read-only (`PVEAuditor`) role; VM start/stop is a later, separately-authorized capability.

### 6.2 Command catalog

Only named, parameterless (or strictly typed) commands, e.g.:

| Name | Node capability | Command | Parser |
|---|---|---|---|
| `gpu_status` | `nvidia_smi` | `nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader,nounits` | CSV → metrics |
| `load` | any unix | `cat /proc/loadavg` (Linux) / `sysctl -n vm.loadavg` (macOS) | floats |
| `ollama_ps` | `ollama` | HTTP `GET /api/ps` | JSON |
| `suspend` | `suspendable` | `systemctl suspend` (Linux) | exit code; **requires confirmation** |

Each call: `asyncssh` connection with 5 s connect / 15 s command deadline, one retry for connect errors only, result written as an observation in the same code path. WoL is sent from the Proxmox-hosted worker (same L2) — sending a packet is recorded as `waking`, never as `online`.

---

## 7. Process and deployment view

| Process | Runs on | Role | Start |
|---|---|---|---|
| PostgreSQL 17 + pgvector ≥ 0.8 | Proxmox LXC `brain-db` | Only datastore | systemd |
| Caddy | Proxmox LXC `brain-app` | LAN TLS (internal CA), serves `web/dist`, proxies `/api` | systemd |
| `ai-second-brain api` (uvicorn) | `brain-app`, bound to 127.0.0.1 | FastAPI + SSE | systemd |
| `ai-second-brain worker` | `brain-app` | procrastinate worker: indexing, sleep cycle, reconcile, hardware polls | systemd |
| `ai-second-brain sync obsidian` | Wherever the vault lives (Syncthing'd copy on `brain-app`, or the Mac) | File events → enqueue | systemd / launchd |
| `ai-second-brain mcp` *(phase 8)* | Client machine | stdio MCP server spawned by the client | client |
| Ollama | Workstation (GPU), Proxmox LXC (CPU), optional Mac | Private tier | systemd / app |

**Node is a build-time dependency only.** `just build` produces static assets in `web/dist`, and Caddy serves them. Production runs no Node process, which keeps the runtime surface to Python + Postgres + Caddy.

**Dev loop:** `just dev` starts Postgres (compose), `uvicorn --reload`, the worker and `vite dev` (which proxies `/api` to uvicorn) together, with prefixed logs. `just check` runs ruff, pyright, pytest, the Biome check, tsc, Vitest and the stale-client check.

Vault access: the simplest robust option is to Syncthing the Obsidian vault to `brain-app` read-only and run the watcher + reconciler there. Watching a vault over SMB/NFS from another host loses events.

Observability sized for one person: structured JSON logs (no content), a `ai-second-brain doctor` command that checks DB, migrations, embedding space, Ollama hosts, SSH reachability and job backlog, and the morning digest as the "dashboard". Backups: nightly encrypted `pg_dump` to the NAS / off-site; quarterly restore test.

---

## 8. Error handling and reliability

| Failure | Behavior |
|---|---|
| Embedding fails mid-revision | Transaction rolls back; previous revision stays current; job retries with backoff (3×), then `failed` shown in `doctor`/digest |
| Duplicate event / re-run | `UNIQUE(source_id, content_hash)` + job `queueing_lock` make it a no-op |
| Missed file events | Nightly reconcile scan diffs vault vs `sources` |
| Note deleted | Tombstone (`deleted_at`); excluded from search; purge after 30 days unless restored |
| LLM output invalid in sleep cycle | Schema validation, one retry, then flagged; never partial edges |
| Workstation doesn't wake | Sleep cycle falls back to CPU host or defers; digest says so |
| Local model down in private chat | Clear error, no cloud fallback |
| SSH timeout | Observation `unreachable` with error category; never "offline" |
| DB unavailable | API returns 503 with a `doctor` hint and the UI shows a system banner; the sync watcher buffers to a local journal file and replays |
| SSE stream drops mid-answer | Turn is committed only on `done`; UI shows "interrupted — retry", with no partial turn in history |

---

## 9. Delivery phases

Aligns with the assessment's decomposition; each phase ends with a usable system.

| # | Phase | Exit criterion | Depends on |
|---|---|---|---|
| 0 | Local quality spike | 20 bilingual questions, ≥ 16 grounded answers, measured latency on Proxmox CPU and workstation GPU | — |
| 1a | Foundation | Monorepo skeleton; `just setup/dev/check` work on a clean machine; dbmate schema; FastAPI health; SPA shell with design tokens, login and layout; CI | — |
| 1b | Private chat (web) | Routing rules from the [routing spec](../superpowers/specs/2026-09-29-private-chat-routing-design.md) §4–§8 reimplemented behind `/api/sessions` with SSE; chat screen with mode badge and source list; egress tests pass — **delivered** ([spec](../superpowers/specs/2026-09-29-phase-1b-private-chat-design.md)) | 1a |
| 2a | Durable vault ingestion | Initial vault scan + watcher + reconcile; crash/retry/delete fixtures pass; Sources screen — **delivered** ([spec](../superpowers/specs/2026-09-30-phase-2a-vault-ingestion-design.md)) | 1a |
| 2b | Search + chat retrieval + capture | Hybrid FTS + vector search API and page; the real Retriever in private chat; the capture box | 2a |
| 3 | Embedding evaluation (bake-off vs bge-m3; add a space only if it wins) | recall@10 on the eval set compares MiniLM/e5 against the bge-m3 default; a second space is built only if it wins | 2b |
| 4 | Knowledge graph + sleep cycle | Entities/edges from nightly job; digest; review queue; idempotent reruns | 2 |
| 5 | Hardware observe/wake | Truthful state fixtures; WoL measured per node; sleep cycle uses workstation | 1 |
| 6 | Document intelligence | PDF invoice/contract, email, git adapters with fixtures and provenance | 2, 4 |
| 7 | Salience + dormancy | Report-only for 30 days, then enabled; restore works | 4 |
| 8 | Omni-search + resume + MCP | Compound prompt returns traceable partial success; `resume` page; MCP returns shareable only by default | 4, 5 |

Phases 0 and 1a can run in parallel. 1b and 2 can run in parallel after 1a. Phase 5 is independent of 2–4. Every phase ships its UI screens together with its API; there is no separate "frontend phase".

---

## 10. What to revisit as it grows

- **Embedding space count** — keep at most two live spaces; drop the old one after switching.
- **Graph depth** — if multi-hop queries (> 3 hops) become common, evaluate Apache AGE (Cypher inside Postgres) before a separate graph DB.
- **FTS language** — if Polish recall is weak, add a Polish dictionary (e.g. an ispell/hunspell config) or rely on multilingual embeddings + re-ranker.
- **Re-ranking** — add a local cross-encoder (e.g. bge-reranker) once the eval set shows ranking, not recall, is the problem.
- **Async**: the API is async (FastAPI + psycopg async pool). CPU-bound work (embedding, PDF parsing) runs in the worker, never in request handlers.
- **Offline/PWA**: if the UI is used from the MacBook away from home, add a WireGuard tunnel. Never expose the API publicly.
- **More users / devices** — would require auth on every interface and per-user sensitivity; explicitly out of scope today.

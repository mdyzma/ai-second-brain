# Architecture documentation

This is the target architecture for building Second Brain as a **greenfield** system from the vision in [`docs/second-brain-prompt.md`](../second-brain-prompt.md): a private-by-default knowledge graph with nightly consolidation, salience/dormancy, document intelligence, LAN hardware orchestration and MCP. The main interface is a React web UI.

**Status:** Proposed (2026-09-29). Nothing here is implemented.

**Fixed owner decisions:** the Phase 1 MVP code is disposable; **uv** manages Python; **just** is the command runner across the whole stack; **Node + React** is the main web UI; **PostgreSQL** is the main storage.

## Reading order

| # | Document | Read it for |
|---|---|---|
| 1 | [product-brainstorm.md](product-brainstorm.md) | Why build this, jobs-to-be-done, top ideas, **open questions for the owner** |
| 2 | [system-design.md](system-design.md) | Requirements, repo layout, API surface, data model, flows, privacy, hardware, deployment, phases |
| 3 | [tech-stack-evaluation.md](tech-stack-evaluation.md) | **TypeScript evaluation** and a verdict on every technology in the prompt, plus bugs in its samples |
| 4 | [adr/](adr/) | Individual decisions with alternatives |
| 5 | [design-system-audit.md](design-system-audit.md) | Vocabulary audit, tokens, React components, accessibility bar |

## Decisions at a glance

| ADR | Decision |
|---|---|
| [0001](adr/0001-modular-monolith.md) | Greenfield monorepo; the backend is a Python modular monolith, the UI is a separate SPA |
| [0002](adr/0002-postgres-single-datastore.md) | PostgreSQL 17 + pgvector is the only datastore; no Redis, no graph DB |
| [0003](adr/0003-postgres-job-queue.md) | procrastinate (Postgres queue) instead of Celery + Redis |
| [0004](adr/0004-data-access-and-migrations.md) | psycopg 3 (async) + SQL; dbmate migrations; no SQLAlchemy/asyncpg |
| [0005](adr/0005-local-inference-topology.md) | Ollama on the RTX 5090 on demand (woken nightly) + Proxmox CPU fallback; never falls back to the cloud |
| [0006](adr/0006-embedding-spaces.md) | Versioned embedding spaces; multilingual local embeddings via Ollama; no cloud embeddings |
| [0007](adr/0007-mcp-as-adapter.md) | MCP server is a thin adapter, shareable-only by default, read-only tools |
| [0008](adr/0008-hardware-execution.md) | asyncssh + allowlisted command catalog; truthful node states |
| [0009](adr/0009-monorepo-toolchain.md) | uv + pnpm + dbmate, all behind a root `justfile` |
| [0010](adr/0010-web-ui-stack.md) | React 19 + strict TypeScript + Vite SPA, TanStack, Tailwind v4 + shadcn/ui; Node at build time only |
| [0011](adr/0011-backend-language-python-vs-typescript.md) | Python vs TypeScript backend evaluated: Python for now, with explicit conditions that would flip it to TypeScript |
| [0012](adr/0012-salience-without-popularity-bias.md) | Salience is a bounded ranking prior; staleness needs evidence; distinctiveness protects one-off ideas; dormant items revive by association |

## Principles

1. **Local by default.** Private content reaches only LAN-hosted models. One gateway enforces this, and tests observe egress.
2. **Never lose an acknowledged import.** Durable staging, atomic revision swaps, tombstones instead of deletes.
3. **Always cite.** Sources appear before the answer; actions produce receipts.
4. **Forget only with consent; protect the long tail.** Relevance dominates ranking. Staleness needs evidence (superseded, expired). Only the user archives. Unique one-off ideas are resurfaced, not buried.
5. **One datastore, few processes.** One person can operate it; no Node at runtime.
6. **Truthful states.** Unknown ≠ offline; a sent packet ≠ an awake machine.

## Relation to earlier specs

- [Assessment](../superpowers/specs/2026-09-29-second-brain-assessment.md): its findings on privacy, durability, lifecycle and hardware still stand. Its advice to *keep Poetry, `src/ai_second_brain` and the existing layout* is **superseded** by the greenfield decision and ADR-0009.
- [Private chat routing spec](../superpowers/specs/2026-09-29-private-chat-routing-design.md): its routing rules (§4 privacy/session rules, §6 provider contract, §8 egress-observing tests) carry over unchanged. Its CLI user contract (§3) and the component layout (§5) need a short revision targeting the API + web UI (phase 1b).

## Maintaining these docs

- To change a decision, add a new ADR that supersedes the old one, and set the old one's status to `Superseded by ADR-XXXX`.
- Each delivery phase in [system-design.md §9](system-design.md#9-delivery-phases) gets its own spec under `docs/superpowers/specs/` before implementation.
- The migration files in `db/migrations/` are the source of truth for the schema; update §3 when they diverge.

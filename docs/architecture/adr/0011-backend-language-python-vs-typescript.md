# ADR-0011: Backend language — Python vs TypeScript

**Status:** Proposed (recommendation: Python backend, TypeScript everywhere in the web app)
**Date:** 2026-09-29
**Deciders:** Michal Dyzma

## Context

The web UI is React on Node, so TypeScript is in the stack regardless. uv manages Python. The old code is disposable, so there is no sunk cost in either direction. The question is whether the *backend* (API, worker, ingestion, hardware, MCP) should also be TypeScript, giving a single-language stack, or stay Python.

What the backend must do, and how each language covers it (library names checked as of 2026-09; verify versions at implementation):

| Capability | Python | TypeScript / Node | Edge |
|---|---|---|---|
| HTTP API + SSE + OpenAPI | FastAPI (Pydantic → OpenAPI) | Hono / Fastify + Zod (`@hono/zod-openapi`), or tRPC | Tie. TS avoids codegen: types are shared directly |
| Postgres + pgvector | psycopg 3 + `pgvector` adapter | `postgres` / `pg` + `pgvector` npm, Drizzle or Kysely (both support vector columns) | Tie |
| Postgres job queue | procrastinate | **graphile-worker** or **pg-boss** (mature, cron support) | Tie, slight TS edge (graphile-worker is very robust) |
| Local embeddings | sentence-transformers in-process (torch, heavy) | transformers.js (ONNX) in-process, **or** Ollama `/api/embed` over HTTP | Tie if embeddings go through **Ollama** (bge-m3 is available there); Python wins only for in-process GPU/CPU batching and model experimentation |
| LLM calls | `anthropic`, `httpx` → Ollama | `@anthropic-ai/sdk`, `ollama` npm | Tie |
| MCP server | official Python SDK | official **TypeScript SDK** (the reference implementation) | Slight TS edge |
| SSH / WoL / Proxmox | asyncssh, wakeonlan, proxmoxer | `ssh2`, WoL packet is ~20 lines with `dgram`, `proxmox-api` | Tie; Python libs are a bit more battle-tested for Proxmox |
| PDF layout-aware extraction (invoices, tables) | **pdfplumber**, camelot, `ocrmypdf` + Tesseract, docling | pdf.js / `unpdf` (text only, weak on tables), OCR via tesseract.js | **Python, clearly** |
| Email `.eml` / `.mbox` | stdlib `email`, `mailbox` | `mailparser`, mbox splitting by hand | Python slight |
| Git history analysis | GitPython / pygit2 / subprocess | `simple-git` / isomorphic-git / subprocess | Tie |
| Structured LLM extraction (JSON schema validation) | Pydantic | Zod | Tie |
| Retrieval evaluation (recall@k, notebooks, ragas-style tooling) | Rich ecosystem, Jupyter | Thin | **Python** |
| Type safety end to end | Pydantic + pyright; types cross to TS via OpenAPI codegen | One type system, no codegen | **TypeScript** |
| Cognitive load for a solo developer | Two languages, two toolchains (uv + pnpm), all run through just | One language, one package manager | **TypeScript** |

## Options Considered

### Option A: Python backend + TypeScript web (recommended)
| Dimension | Assessment |
|---|---|
| Complexity | Medium: two toolchains, bridged by just + OpenAPI codegen |
| Fit to hardest problems | High: documents, embeddings, evaluation |
| Owner preference | Matches "uv manages Python" |

**Pros:** best tools for the two riskiest technical areas (document intelligence and retrieval quality/evaluation); embedding experiments in-process. **Cons:** a contract boundary to maintain (mitigated by generated client + CI staleness check); context switching between languages.

### Option B: TypeScript full stack (Node backend: Hono + Drizzle + graphile-worker + Ollama embeddings)
| Dimension | Assessment |
|---|---|
| Complexity | Low: one language, shared Zod schemas, no codegen |
| Fit to hardest problems | Medium-low: PDF/table extraction and evaluation are weak |

**Pros:** shared types and validation between UI and API; one package manager; first-class MCP SDK; excellent async I/O for SSH fan-out. **Cons:** invoice/contract extraction quality would suffer, or you would need a Python sidecar anyway; weak evaluation tooling; the uv/Python investment is unused.

### Option C: TypeScript API + Python extraction worker (hybrid)
The API, UI, MCP, hardware and search run in TS. A Python worker consumes `ingest` jobs from the same Postgres queue (the worker polls the same job tables through a small adapter, or both sides use a plain `jobs` table with `SKIP LOCKED`) and does PDF/email/embedding work.

**Pros:** each language where it is strongest. **Cons:** domain logic (chunking, sensitivity rules, schema access) is split across two languages. The queue must be language-neutral, which rules out procrastinate/graphile-worker as-is. Two data-access layers must agree on one schema. Highest total complexity for a solo project.

## Trade-off Analysis

- The deciding factors are **document intelligence** and **retrieval evaluation**. Both are core to the product (paperwork facts, and the Phase 0 quality gate) and are both much stronger in Python. Everything else is roughly a tie.
- TypeScript's biggest win, shared types, is mostly recovered in Option A. Pydantic schemas generate OpenAPI, which generates TS types, and CI makes drift a build failure.
- If Phase 0 shows that generation quality dominates and document extraction is deferred or delegated to a local vision model through Ollama, the Python advantage shrinks. **Option B would then become the better choice.** This is the condition that would flip the decision.
- Option C is the worst of both for one developer; only choose it if a team forms.

## Decision

Option A. Python 3.12 backend managed by uv. **TypeScript in strict mode** for all web code (no JavaScript files, `strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`). The API contract is generated from Pydantic via OpenAPI. Embeddings are served through **Ollama's embed endpoint** by default, which keeps the backend light and leaves the language choice reversible. sentence-transformers is used only in the evaluation harness.

## Consequences

- Easier: pdfplumber/OCR, the embedding/eval harness, notebooks for retrieval tuning.
- Harder: two toolchains. just hides this (`just setup`, `just check`), and the codegen step must stay in CI.
- Revisit: after Phase 0 and the first PDF-extraction spike. If extraction moves to an Ollama vision model and eval needs stay modest, re-evaluate Option B before Phase 4 while the backend is still small.

## Action Items
1. [ ] Phase 0 eval harness in Python (`backend/eval/`), reading the same DB.
2. [ ] PDF spike: pdfplumber vs an Ollama vision model on 20 real invoices (field accuracy for amount, NIP, dates).
3. [ ] Record the outcome here and confirm or supersede this ADR.

# ADR-0001: Modular-monolith backend in a greenfield monorepo

**Status:** Proposed
**Date:** 2026-09-29
**Deciders:** Michal Dyzma

## Context

The Phase 1 MVP was a first attempt and is discarded, so this is a greenfield build. The prompt proposes FastAPI + Celery + Redis + SQLAlchemy + an MCP host/server. The system has one user, ~0.5 M chunks at the high end, and one operator. It spans a Python backend and a React/TypeScript UI ([ADR-0010](0010-web-ui-stack.md), [ADR-0011](0011-backend-language-python-vs-typescript.md)). Independent capabilities (ingestion, lifecycle, hardware, search, MCP) must be deliverable one at a time.

## Decision

Build the backend as a single deployable Python package (`backend/src/ai_second_brain`) with bounded modules (`sources`, `knowledge`, `lifecycle`, `search`, `llm`, `conversation`, `hardware`, `jobs`, `interfaces`). Run it as several process roles (API, worker, MCP, admin CLI) from one codebase. The React SPA is a separate app in the same repo that talks only to the HTTP API. Module boundaries are enforced with `import-linter` contracts in `just check`.

## Options Considered

### Option A: Modular monolith + SPA (chosen)
| Dimension | Assessment |
|---|---|
| Complexity | Low: one backend deployable, one datastore, static UI |
| Cost | Two small LXCs |
| Scalability | Far beyond the 1-user load |
| Familiarity | Standard FastAPI + React shape |

**Pros:** phased delivery; shared domain types inside the backend; one migration history; one test suite per app. **Cons:** boundaries need discipline (linter); one bad dependency affects all backend roles.

### Option B: Prompt layout (FastAPI + Celery workers + Redis + SQLAlchemy)
**Pros:** familiar tutorial shape. **Cons:** Redis and Celery add two services whose jobs Postgres already covers (ADR-0002, ADR-0003).

### Option C: Microservices (ingestion, search, hardware, LLM gateway as services)
**Pros:** hard network isolation, e.g. an LLM gateway as the only egress point. **Cons:** network contracts, deployment and tracing for a solo operator; no scale driver.

## Trade-off Analysis

The only strong argument for service separation is privacy isolation of egress. A single `llm` module can be the sole importer of provider SDKs (lint-enforced) and backed by egress tests. That gets the isolation more cheaply. If stronger isolation is ever needed, `llm` can be lifted into its own process behind the same interface, with firewall rules limiting cloud egress to it.

## Consequences

- Easier: phased delivery with UI and API shipped together per phase.
- Harder: nothing stops a careless import except the linter, so keep it in `just check`.
- Revisit: if the MCP server needs a different dependency set, split it into its own uv workspace member.

## Action Items
1. [ ] Scaffold the monorepo per [system-design §2.2](../system-design.md#22-repository-layout) and [ADR-0009](0009-monorepo-toolchain.md).
2. [ ] Add `import-linter` contracts for the `llm` and `hardware` SDK imports.
3. [ ] Remove the MVP code (`src/`, `tools/`, `tests/`, `pyproject.toml`, `poetry.lock`, `sql_migrations/`) in the scaffolding PR.

# ADR-0002: PostgreSQL + pgvector as the single datastore (no Redis)

**Status:** Proposed
**Date:** 2026-09-29
**Deciders:** Michal Dyzma

## Context

The prompt uses PostgreSQL + pgvector for LTM and Redis for STM cache and Celery broker. It also suggests Neo4j-style GraphRAG projects as inspiration. Docs disagree on the Postgres version (16 in prompt, 17 in `docker-compose.yml`, 18 in README). Requirements: relational integrity (projects ↔ invoices ↔ emails), vectors, full-text for identifiers (NIP, hostnames), a skill tree, a job queue, and durable staging of new notes.

## Decision

Use one PostgreSQL instance for everything: relational data, vectors (pgvector ≥ 0.8, HNSW, `halfvec`), full-text (`tsvector`, `simple` config), graph (entities + edges + recursive CTEs), job queue (see ADR-0003), sessions and hardware observations. Do not add Redis. Pin **PostgreSQL 17** (matches Compose) for dev and prod; verify the Proxmox server version and migrate it to 17 if it differs, before schema v2.

## Options Considered

### Option A: PostgreSQL only (chosen)
| Dimension | Assessment |
|---|---|
| Complexity | Low |
| Cost | One LXC |
| Scalability | ~1 M vectors comfortably on 8–16 GB RAM |
| Familiarity | Already used |

**Pros:** transactional ingestion (revision swap + chunks + embeddings in one commit); one backup; hybrid SQL+vector filters in one query. **Cons:** HNSW builds are memory-hungry (`maintenance_work_mem`); vector workloads share the instance with OLTP.

### Option B: Postgres + Redis
**Pros:** fast ephemeral cache; Celery broker. **Cons:** "volatile STM buffer" in Redis loses acknowledged notes on restart (assessment finding #5); second service to back up/monitor; the latency gain is irrelevant at 1 user.

### Option C: Postgres + dedicated vector DB (Qdrant/Milvus) or graph DB (Neo4j)
**Pros:** richer vector/graph features. **Cons:** cross-store consistency; filters on relational data become two-phase; no scale need.

## Trade-off Analysis

Everything the prompt stores in Redis is either (a) durable data mislabeled as volatile, which belongs in Postgres, or (b) session/telemetry state that Postgres handles at this load with trivial cost. Graph queries needed (skill subtree, project → invoices → counterparties, 1–2 hop expansion) are well within recursive CTEs.

## Consequences

- Easier: backups (`pg_dump`), consistency, testing with one container.
- Harder: tuning for HNSW builds; must set `hnsw.iterative_scan` for filtered queries.
- Revisit: Apache AGE if Cypher-style multi-hop queries become central; a separate vector store only above ~10 M vectors.

## Action Items
1. [ ] Verify production Postgres/pgvector versions; record them in README.
2. [ ] Fix README (says 18) and prompt DDL (`CREATE EXTENSION pgvector` → `vector`).
3. [ ] Add encrypted nightly `pg_dump` and a restore test.

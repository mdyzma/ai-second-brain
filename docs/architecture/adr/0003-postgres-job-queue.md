# ADR-0003: Postgres-backed job queue (procrastinate) instead of Celery + Redis

**Status:** Accepted (2026-09-30)
**Date:** 2026-09-29
**Deciders:** Michal Dyzma

## Context

Background work: index revisions (seconds, frequent), nightly sleep cycle (minutes–hours), reconcile scans, hardware polling, salience recompute, bulk imports (email archives). Needs retries, deduplication, periodic schedules, and visibility into failures. The prompt picks Celery + Redis.

## Decision

Use **procrastinate** (PostgreSQL-based task queue for Python, psycopg 3, sync and async tasks, periodic/cron tasks, queueing locks) run as `ai-second-brain worker`. Jobs are enqueued in the same transaction as the data they refer to.

## Options Considered

### Option A: procrastinate (chosen)
| Dimension | Assessment |
|---|---|
| Complexity | Low — tables in existing DB |
| Cost | No new service |
| Scalability | Hundreds of jobs/s; far above need |
| Familiarity | New library, small API |

**Pros:** transactional enqueue (no "row committed but job lost"); `queueing_lock` dedupes re-index of the same source; periodic tasks replace cron. **Cons:** smaller community than Celery; ties queue to DB availability (acceptable — nothing works without the DB anyway).

### Option B: Celery + Redis
**Pros:** very mature, rich tooling (Flower). **Cons:** extra broker; no transactional enqueue; heavier config; historically awkward with asyncio.

### Option C: systemd timers + plain CLI commands, plus a hand-rolled `jobs` table with `FOR UPDATE SKIP LOCKED`
**Pros:** zero dependencies. **Cons:** re-implementing retries, backoff, locks and scheduling.

## Trade-off Analysis

Option C is a valid fallback if procrastinate proves problematic; the job functions are plain Python so the switch is cheap. Celery's strengths (distributed workers, huge throughput) address problems this system does not have.

## Consequences

- Easier: one datastore; atomic "save revision + enqueue index".
- Harder: must keep job payloads small (ids only, never content — also a privacy rule).
- Revisit: if long GPU jobs need to run *on the workstation*, add a second worker there consuming a `gpu` queue.

## Implementation notes (Phase 2a)

- **Vendored schema.** procrastinate's schema is committed as a dbmate migration rather than applied by the library, so `db/schema.sql` stays the single source of truth.
- **Queue after commit.** Jobs are deferred after the transaction that saves the revision commits, not inside it. A crash in between leaves a `pending` revision with no job, and the reconcile re-queues it.
- **Stalled jobs.** Workers (not jobs) heartbeat; reconcile resets `doing` jobs whose worker's heartbeat is more than 10 minutes old, so a crashed worker's jobs are retried.
- **Reconcile timer.** The scheduled reconcile is an asyncio timer inside the worker process (every `SB_RECONCILE_MINUTES`, plus one at startup and at most one every 10 s when the watcher asks for a rescan), not a procrastinate periodic task or an external scheduler. "Scan now" defers a `reconcile_vault` job instead.
- **Priorities.** Index and reconcile jobs are deferred with priority 10 and embed jobs with 0, so an edit is indexed ahead of a long embedding backlog.
- **Queues.** `ingest` (parse, chunk and index a source) and `embed` (embed a revision's chunks for a space), concurrency 2. `nightly` and `hardware` (later `gpu`) follow with their phases.

## Action Items
1. [ ] Spike: index + periodic task under procrastinate against the dev Compose DB.
2. [x] Define queues: `ingest` and `embed` (Phase 2a); `nightly`, `hardware` (later `gpu`) follow with their phases.

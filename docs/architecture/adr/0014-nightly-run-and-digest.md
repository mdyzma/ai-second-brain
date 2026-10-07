# ADR-0014: A nightly run on a 15-minute tick, and a live digest

**Status:** Accepted (2026-10-07)
**Date:** 2026-10-07
**Deciders:** Michal Dyzma

## Context

Phase 4a extracts the graph only when the owner starts it. Phase 4b ([spec](../../superpowers/specs/2026-10-04-phase-4b-nightly-digest-design.md)) runs extraction every night and shows the owner a morning **Digest**: what the night produced and what still needs a decision.

The job scheduler is procrastinate ([ADR-0003](0003-postgres-job-queue.md)). Its cron runs in **UTC** and **drops a tick that is more than 10 minutes late**. A fixed cron entry would therefore fire at the wrong local hour for half the year (daylight saving) and would be skipped for the whole night if the worker was briefly down at the set time. The wish is "about 02:00 local time, every night, even if the worker restarted at 01:55".

## Decision

1. **A 15-minute tick decides; the decision lives in code.** The periodic job `nightly_tick` runs on the `nightly` queue with cron `*/15 * * * *` and the queueing lock `nightly-tick`. The `nightly` queue is served by the existing `[ingest, embed]` worker loop. On each tick, `should_start` compares the local wall clock with `SB_NIGHTLY_AT` in the owner's zone and starts a run when that time has been reached and no scheduled run has started today. A missed tick is made up by the next one.
2. **The zone is an IANA name, resolved once.** `SB_TIMEZONE` empty means the host's real zone through `tzlocal`, so daylight saving is respected. A bad value fails settings validation at startup. `tzdata` and `tzlocal` are dependencies, so the zone database does not depend on the host.
3. **A run is a row.** `nightly_runs` records the run and the notes it queued (new, changed and failed). `SB_NIGHTLY_MAX_NOTES` (500) caps one night, and `SB_NIGHTLY_MAX_HOURS` (8) is when a run stops waiting. The run also re-extracts notes whose `EXTRACTOR_VERSION` is out of date, capped per night, which answers the revisit line of [ADR-0013](0013-knowledge-graph-review.md).
4. **Extraction is not duplicated.** A run queues the existing `graph_extract_revision` jobs on the `extract` queue. It adds no second extraction path.
5. **A run closes only when a tick finds the extract queue drained.**
6. **The digest is live, not a snapshot.** `GET /api/digest` computes the digest from the database when it is read. Its **To review** section uses exactly the same visibility rule as the Review screen's Links tab, through the shared SQL fragments in `graph/queries.py`, so the two screens cannot disagree. `/` opens the Digest, and the Digest nav item shows the to-review count as a badge.
7. **Manual control.** `POST /api/nightly/run` ("Run now"), `ai-second-brain nightly run` (`just nightly`) and `ai-second-brain nightly status` (`just nightly-status`) start or inspect a run. `GET /api/digest/{date}` and `GET /api/nightly/runs` read past ones.

## Options Considered

| Option | Pros | Cons |
|---|---|---|
| **A. A 15-minute tick plus a local-time decision in code (chosen)** | Right local hour all year; a late or missed tick is caught up; the decision is a pure, testable function | One cheap job every 15 minutes; a run can start up to 15 minutes after the set time |
| B. A fixed UTC cron entry | Simplest | Wrong hour after a daylight-saving change; skipped when the tick is more than 10 minutes late |
| C. An asyncio timer in the worker, like the reconcile | Local time is easy | Not visible in the queue; no queueing lock; lost if the worker restarts at the wrong moment |
| D. A digest frozen at 06:00 | The digest reads like a report | It is wrong the moment the owner starts reviewing, and needs its own job and store |

## Consequences

- **The digest empties as the owner reviews.** Reviewed items drop out; this is the point of an inbox. A past date's digest shows what is still open, not an archive.
- **A late close.** A run closes only when a tick finds the extract queue drained, so a run started with Run now can show "Reading notes x of y" for up to 15 minutes after its work finishes. This is known behaviour; a later change may improve it.
- **Known, accepted limitations:**
  - A hand-started `graph-extract` during a nightly run keeps that run open, and its results count toward the run (spec §5.3).
  - Past runs' progress and failure counts can drop when a later run retries the same note, because each extraction keeps only its latest attempt.
- **The schedule must be off in e2e.** The e2e harness runs with `SB_NIGHTLY_ENABLED=false`, so a tick cannot start a run in the middle of a test; the specs start runs with Run now. The e2e reset script refuses any database not named `*_test`.
- Revisit: when Phase 5 lets the sleep cycle wake the GPU workstation, the run may need to wait for the node ([system design §4.2](../system-design.md#42-sleep-cycle-consolidation)).

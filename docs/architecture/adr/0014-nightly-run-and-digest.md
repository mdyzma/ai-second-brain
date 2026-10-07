# ADR-0014: A nightly run on a 15-minute tick, and a live digest

**Status:** Accepted (2026-10-07)
**Date:** 2026-10-07
**Deciders:** Michal Dyzma

## Context

Phase 4a extracts the graph only when the owner starts it. Phase 4b ([spec](../../superpowers/specs/2026-10-04-phase-4b-nightly-digest-design.md)) runs extraction every night and shows the owner a morning **Digest**: what the night produced and what still needs a decision.

The job scheduler is procrastinate ([ADR-0003](0003-postgres-job-queue.md)). Its cron runs in **UTC** and **drops a tick that is more than 10 minutes late**. A fixed cron entry would therefore fire at the wrong local hour for half the year (daylight saving) and would be skipped for the whole night if the worker was briefly down at the set time. The wish is "about 02:00 local time, every night, even if the worker restarted at 01:55".

## Decision

1. **A 15-minute tick decides; the decision lives in code.** The periodic job `nightly_tick` runs on the `nightly` queue with cron `*/15 * * * *` and the queueing lock `nightly-tick`. The existing ingest/embed worker loop also serves the `nightly` queue (it runs `[ingest, embed, nightly]`), so a tick never takes an extract slot. On each tick, `should_start` compares the local wall clock with `SB_NIGHTLY_AT` in the owner's zone and starts a run when that time has been reached and no scheduled run has started today. A missed tick is made up by the next one.
2. **The zone is an IANA name, resolved once.** `SB_TIMEZONE` empty means the host's real zone through `tzlocal`, so daylight saving is respected. A bad value fails settings validation at startup, and so does an `SB_NIGHTLY_AT` later than 23:45, the last tick of a day. `tzdata` and `tzlocal` are dependencies, so the zone database does not depend on the host.
3. **A run is a row.** `nightly_runs` records the run and the notes it queued (new, changed and failed). `SB_NIGHTLY_MAX_NOTES` (500) caps one night, and `SB_NIGHTLY_MAX_HOURS` (8) is when a run stops waiting. The run also re-extracts notes whose `EXTRACTOR_VERSION` is out of date, capped per night, which answers the revisit line of [ADR-0013](0013-knowledge-graph-review.md).
4. **Extraction is not duplicated.** A run queues the existing `graph_extract_revision` jobs on the `extract` queue. It adds no second extraction path.
5. **A run closes when the extract queue has drained, or after `SB_NIGHTLY_MAX_HOURS`.** `close_open_run` is stateless. Each tick calls it, and so does every digest read (close-on-read). A run still `running` with zero counts is being queued, so it is left open for five minutes; after that its start is taken to have died, and it is marked failed with `start_interrupted` so the next tick retries the day. A failed start is recorded on a fresh connection.
6. **The digest is live, not a snapshot.** `GET /api/digest` computes the digest from the database when it is read. Its **To review** section uses exactly the same visibility rule as the Review screen's Links tab, through the shared SQL fragments in `graph/queries.py`, so the two screens cannot disagree. It lists the run's own items, and `review.open_total` counts everything awaiting review from any run. `/` opens the Digest; the Digest nav item shows `open_total` as a badge, and "All caught up" appears only when `open_total` is zero.
7. **Manual control.** `POST /api/nightly/run` ("Run now"), `ai-second-brain nightly run` (`just nightly`) and `ai-second-brain nightly status` (`just nightly-status`) start or inspect a run. `GET /api/digest/run/{run_id}`, `GET /api/digest/{date}` (the latest run on that date) and `GET /api/nightly/runs` read past ones; the web picker selects runs by id.

## Options Considered

| Option | Pros | Cons |
|---|---|---|
| **A. A 15-minute tick plus a local-time decision in code (chosen)** | Right local hour all year; a late or missed tick is caught up; the decision is a pure, testable function | One cheap job every 15 minutes; a run can start up to 15 minutes after the set time |
| B. A fixed UTC cron entry | Simplest | Wrong hour after a daylight-saving change; skipped when the tick is more than 10 minutes late |
| C. An asyncio timer in the worker, like the reconcile | Local time is easy | Not visible in the queue; no queueing lock; lost if the worker restarts at the wrong moment |
| D. A digest frozen at 06:00 | The digest reads like a report | It is wrong the moment the owner starts reviewing, and needs its own job and store |

## Consequences

- **The digest empties as the owner reviews.** Reviewed items drop out; this is the point of an inbox. A past run's digest lists only its items that are still proposed, not an archive.
- **A prompt close.** Because digest reads also close a drained run, "Reading notes x of y" turns into the summary on the next poll after the work finishes, not at the next 15-minute tick. The cost is one extra query per digest read.
- **Known, accepted limitations:**
  - A hand-started `graph-extract` during a nightly run keeps that run open, and its results count toward the run (spec §5.3).
  - Past runs' progress and failure counts can drop when a later run retries the same note, because each extraction keeps only its latest attempt.
- **The schedule must be off in e2e.** The e2e harness runs with `SB_NIGHTLY_ENABLED=false`, so a tick cannot start a run in the middle of a test; the specs start runs with Run now. The e2e reset script refuses any database not named `*_test`.
- Revisit: when Phase 5 lets the sleep cycle wake the GPU workstation, the run may need to wait for the node ([system design §4.2](../system-design.md#42-sleep-cycle-consolidation)).

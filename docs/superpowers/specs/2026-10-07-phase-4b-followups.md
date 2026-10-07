# Phase 4b follow-ups

Known limitations and deferred minor items from the Phase 4b build (the nightly run and the morning digest). None of them blocks use.

## Accepted limitations

- **A hand-started extraction during a nightly run keeps that run open.** If you run `just graph-extract` while a nightly run is in progress, the run waits for those jobs too. Their results count towards that night's digest.
- **Past runs' numbers can shrink.** Each extraction keeps only its latest attempt time. If a later run retries a note, that attempt moves out of the earlier run's window, so the earlier run's progress and failure counts can drop, though never rise.
- **Two periodic deferrers.** The worker runs two job loops, so the 15-minute tick is offered twice. procrastinate's own dedupe and the `nightly-tick` queueing lock make this harmless.

## Deferred from reviews

- **API status codes.**
  - The `already_started` outcome maps to 503 `nightly_failed` in the API and to "failed: unknown" in the CLI. It cannot happen for manual runs.
  - A database error inside `start_run` surfaces as a 500 instead of 503 `database_unavailable`.
- **Test coverage.**
  - API tests exercise only empty digests; populated digests are covered by the digest query tests and e2e.
  - The CLI tests mock the async internals.
  - Web: there are no tests for digest invalidation after a Review decision, or for `?tab=links` search validation.
  - The tombstoned-note entity-confidence rule has no test of its own.
- **Run store.**
  - There is a narrow stale-window race between two concurrent run inserts.
  - Capped queueing has no tests for a cap that straddles pending and failed notes, or for ordering among several failed notes.
- **e2e.**
  - The graph reset could fire while an extract job is still running.
  - `reset-graph.ts` passes a minimal environment to `uv`. If `uv` complains about a missing cache directory, add `USERPROFILE`, `LOCALAPPDATA` and `TEMP`.
- **UI.** A link with no object would render a dangling "—". The current queries never produce one.

## Deferred from the final fix-wave re-review

- **A slow but healthy start is marked interrupted.**
  - A run that is still queueing after 5 minutes is marked `start_interrupted`. That needs a very large `SB_NIGHTLY_MAX_NOTES`.
  - Its jobs still run, but the run's counts are lost.
  - For a manual run, the copy then says it "will try again at the next check", which isn't true.
  - Fix: only mark a run interrupted when no extract jobs exist for it, or raise the grace period with the cap.
- **Past-run views.**
  - On a past run opened with `?run=`, "N more waiting from earlier runs" also counts items from later runs.
  - A 409 busy line clears on the first refetch.
  - "Run now" stays enabled while a different run is open.
- **The badge cost grew.** Each badge or digest read now also checks the open run and counts everything awaiting review, every 60 s, or every 5 s while a run is running. That's fine at personal scale; add an index if it shows up.
- **Spec §9's log list** doesn't name `nightly_run_failed` or `nightly_run_fail_unrecorded`.
- **`nightly_max_hours`** shown for an old timed-out run is today's setting, not the value in force at the time.

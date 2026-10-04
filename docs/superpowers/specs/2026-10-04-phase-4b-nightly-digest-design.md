# Phase 4b: the nightly run and the morning digest

Date: 2026-10-04 · Status: **under review** · Owner: Michal Dyzma
Parent docs: [system design](../../architecture/system-design.md) §4.2 (sleep cycle), §9 · [ADR-0003](../../architecture/adr/0003-postgres-job-queue.md) · [ADR-0013](../../architecture/adr/0013-knowledge-graph-review.md) · builds on [Phase 4a](2026-10-03-phase-4a-knowledge-graph-design.md)

## 1. Purpose and success

Phase 4a built the knowledge graph, but extraction only runs when the owner starts it. 4b runs it every night on its own. Each morning a **Digest** screen shows what the night produced and what still needs the owner's decision.

The digest is a **review inbox**, not a journal. Its job is to get the owner from "the model found things" to "I decided on them" quickly. It works on top of the 4a Review screen and does not replace it. Items the owner has already reviewed drop out of it, so it empties as they work.

**Success (exit criteria):**
1. With the worker running, a run starts by itself once per local day at or after `SB_NIGHTLY_AT`. This holds across DST changes and after the server was off at that time.
2. A run queues new, changed and failed notes for extraction, up to the nightly cap. It closes when those jobs are done.
3. `/digest` is the landing page. It shows the latest run's summary, the proposed entities and links still awaiting review, failures and indexing activity. Past runs can be opened by date.
4. "Run now" and `just nightly` start a run by hand.
5. The digest, the run rows and the logs contain counts, ids, names the owner can already see in Review, and note paths. Logs contain no note text, summaries or entity names.
6. CI is green on Linux and macOS and releases v0.8.0.

## 2. Scope

**In:**
- the `nightly_runs` migration;
- the nightly tick (a procrastinate periodic task) and the run lifecycle;
- a capped variant of 4a's `queue_extraction`;
- the digest queries;
- the nightly and digest APIs;
- the CLI command and its `just` recipe;
- the Digest screen with its nav badge, and the landing redirect;
- tests, docs, ADR-0014 and a screenshot.

**Out:**
- waking and suspending the GPU workstation (Phase 5);
- salience, dormancy, Rediscover and Superseded (Phase 7);
- writing the digest into the vault, and notifications (declined by the owner);
- one-line summaries of each note in the digest;
- the nightly `pg_dump` backup (ADR-0002);
- extracting during the day as notes are indexed.

## 3. Owner decisions

| Question | Decision |
|---|---|
| What the digest is for | A review inbox: what last night found, still awaiting a decision, and what failed. |
| What a run queues | Notes that are new, changed or version-bumped, plus failed ones retried once per night, with a cap per night. |
| Delivery | The web Digest screen only, with a nav badge. |
| Approach | A run record plus a live digest computed from the run's window (no frozen snapshot), and a 15-minute tick instead of a fixed cron. |
| Landing page | `/` redirects to `/digest` (was `/ask`). |

## 4. Data

One new table, in migration `db/migrations/<timestamp>_nightly.sql`:

```sql
CREATE TABLE nightly_runs (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_date       date NOT NULL,                 -- local date (SB_TIMEZONE) the run belongs to
  trigger        text NOT NULL CHECK (trigger IN ('schedule','manual')),
  status         text NOT NULL DEFAULT 'running'
                 CHECK (status IN ('running','complete','failed')),
  window_start   timestamptz NOT NULL,          -- previous run's started_at, or '-infinity'
  started_at     timestamptz NOT NULL DEFAULT now(),
  finished_at    timestamptz,
  queued_new     int NOT NULL DEFAULT 0,
  queued_failed  int NOT NULL DEFAULT 0,
  timed_out      boolean NOT NULL DEFAULT false,
  unavailable    boolean NOT NULL DEFAULT false, -- extraction had no endpoint
  error          text                            -- short code only, never content
);
-- One scheduled run per local day that did not fail; manual runs are unlimited.
CREATE UNIQUE INDEX nightly_runs_scheduled_day ON nightly_runs (run_date)
  WHERE trigger = 'schedule' AND status <> 'failed';
-- At most one run open at a time.
CREATE UNIQUE INDEX nightly_runs_one_open ON nightly_runs ((true)) WHERE status = 'running';
CREATE INDEX nightly_runs_started ON nightly_runs (started_at DESC);
```

**Previous run:**
- A run's `window_start` is the `started_at` of the latest earlier run that is not `failed`.
- If there is no such run, `window_start` is `'-infinity'`. The indexing line then counts all notes, and it is labelled "since the beginning".

**Not used:** `metadata->>'consolidated_at'` from system-design §4.2. 4a's `extractions` table already records which revision was extracted at which version.

## 5. The nightly tick

### 5.1 Schedule

- `nightly_tick` is a procrastinate periodic task with the cron `*/15 * * * *`, the queue `nightly` and the queueing lock `nightly-tick`.
- The worker runs the `nightly` queue in the existing ingest/embed loop, so no third loop is added.
- Procrastinate evaluates cron in UTC and drops a tick that is more than 10 minutes late. The tick therefore does not encode the local time. It decides that itself, every 15 minutes.

Each tick does the following:

1. **Close the open run, if any** (§5.3).
2. **Decide whether to start today's run.** This is the pure function `should_start(now_utc, tz, nightly_at, today_has_scheduled_run, enabled) -> bool`, which is true when all of these hold:
   - the schedule is enabled;
   - `now` converted to `tz` is at or after `nightly_at` on that local date;
   - no scheduled run that has not failed exists for that `run_date`.
3. If it returns true, **start a scheduled run** (§5.2). If no tick ran at 02:00 because the server was off, the first tick after the server comes up starts the run the same day. A day the server is fully off needs no catch-up, because the next run's window starts at the last good run.

**Settings:**

| Setting | Default | Meaning |
|---|---|---|
| `SB_NIGHTLY_ENABLED` | `true` | Turn off the schedule. Manual runs still work. |
| `SB_NIGHTLY_AT` | `02:00` | Local start time, as `HH:MM`, validated. |
| `SB_TIMEZONE` | system zone | An IANA name, validated with `zoneinfo`. Unset uses the host zone. |
| `SB_NIGHTLY_MAX_NOTES` | `500` | Cap on notes queued per run, new and failed together (1–100000). |
| `SB_NIGHTLY_MAX_HOURS` | `8` | Close a run still open after this many hours (1–48). |

### 5.2 Starting a run

`start_run(conn, queue, settings, trigger) -> RunStart` runs in one transaction:

1. Insert the run row with `run_date` set to today's local date and `window_start` set to the previous good run's `started_at`.
   - A scheduled insert conflicting on `nightly_runs_scheduled_day` means another worker won. Return `already_started`.
   - A conflict on `nightly_runs_one_open` means a run is in progress. Return `busy`. The API turns this into 409.
2. If extraction is unavailable (`extract_model_name` is None), set `unavailable = true`, `status = 'complete'` and `finished_at = now()`, then return.
3. Queue extraction with `queue_extraction_capped(conn, queue, version, limit)`:
   - It takes pending revisions first, oldest source first, then failed revisions, together capped at `SB_NIGHTLY_MAX_NOTES`.
   - It reuses 4a's per-revision lock `extract:{revision_id}`. A lock hit is not counted.
   - It returns `(queued_new, queued_failed)`.
4. Store the counts. If both are zero, mark the run `complete` at once.

**Failure while starting:** if any step raises, the transaction rolls back. A second short transaction then records the run as `failed`, with `error` set to a code such as `db_error` or `queue_error`. The digest shows the failed run. Because it is `failed`, the next tick may start a new scheduled run the same day.

### 5.3 Closing a run

- A `running` run becomes `complete`, with `finished_at` set, when no `extract` jobs are waiting or running. This is the same "queued" count 4a's status uses.
- If it has been open longer than `SB_NIGHTLY_MAX_HOURS`, it is closed with `timed_out = true`. Its jobs keep running.
- Closing is stateless, so a worker restart mid-run is safe.
- **Known limitation:** an extraction started by hand during a nightly run (with `just graph-extract`) keeps the run open until it also drains. Its results count towards the run.

## 6. The digest

### 6.1 Window

- **Input window:** `[window_start, started_at)`. This is what was indexed since the previous run.
- **Output window:** `[started_at, finished_at)`, or up to now while running. This is what the run produced.
- Entities (`created_at`), edges (`created_at`) and extractions (`attempted_at`) already have timestamps, so no tracking columns are added.
- Entities and links the owner creates by hand are never `proposed`, so they never appear.

### 6.2 Sections

`digest(conn, run_id) -> Digest` returns:

1. **Run:**
   - date, trigger and status;
   - `timed_out`, `unavailable` and `error`;
   - started and finished times;
   - queued counts;
   - progress: extractions attempted in the output window, against queued.
2. **To review:**
   - Entities created in the output window that are still `proposed`. These are grouped by type with counts, plus the top 5 by confidence: id, name, type and the note they came from.
   - Edges created in the output window that are still `proposed` and visible under 4a's review rules (no rejected endpoint, live source). These come as a count plus the top 5 by confidence, with subject, relation and object.
   - `remaining` is the sum of both counts. The nav badge shows the latest run's `remaining`.
3. **Failed:** extractions with `status = 'failed'` and `attempted_at` in the output window, whose revision is still current. This is a count plus the first 10 by path, with the error code.
4. **Indexed:**
   - sources created in the input window;
   - revisions in it that replaced an earlier one (changed);
   - sources tombstoned in it (deleted).

### 6.3 Copy rules

- **Summary line:** for example, "Last night: 42 notes read, 3 failed, 18 to review."
- **Running:** "Reading notes: 12 of 42."
- **Unavailable:** "Extraction is off: no Ollama endpoint is configured (`SB_OLLAMA_ENDPOINTS`)."
- **Timed out:** "Stopped waiting after 8 hours. Remaining notes will finish in the background."
- **Failed run:** "Last night's run failed to start (db_error). It will try again at the next check."
- **Empty To review:** "All caught up."
- **Failures:** "Retried next night, or run `just graph-extract --failed` now."
- **No runs yet:** "No nightly run yet. The first starts at 02:00, or press Run now."

## 7. API and CLI

Operation ids, under the existing graph access dependency:

- `getDigest` (`GET /api/digest`): the latest run's digest. Returns 200 with `run: null` when no run exists.
- `getDigestByDate` (`GET /api/digest/{date}`): the digest of the latest run on that `run_date`. Returns 404 if there is none and 422 for a bad date.
- `listNightlyRuns` (`GET /api/nightly/runs?limit=30`): newest first, giving id, date, trigger, status and remaining.
- `startNightlyRun` (`POST /api/nightly/run`): starts a manual run. Returns 202 with the run, or 409 `nightly_busy` while a run is open.

CLI:
- `ai-second-brain nightly run` starts a manual run and prints the queued counts.
- `ai-second-brain nightly status` prints the latest run's summary line.
- The root `justfile` gets `just nightly` and `just nightly-status`.

## 8. Web

- **Route `/digest`:** replaces the placeholder.
  - Header: the date picker (from `listNightlyRuns`) and a "Run now" button. "Run now" is disabled while running and shows the busy copy on 409.
  - Sections as in §6.2.
  - Each entity in To review links to `/entities/$entityId`. "Review all" opens `/review`, and "Review links" opens `/review` on its Links tab.
  - Uses the shared screen components and tokens.
  - Headings and lists are accessible. Progress and status changes are announced politely through `aria-live`.
- **Polling:** the digest refetches every 5 s while the run is `running`, otherwise every 60 s. A decision on `/review` invalidates the digest query.
- **Nav badge:** the Digest nav item shows `remaining` from the latest run when it is more than 0, labelled for screen readers ("18 to review").
- **Landing:** `/` redirects to `/digest`.

## 9. Privacy and logging

- The nightly run calls the model only through 4a's extraction jobs, so 4a's local-only rule applies unchanged.
- Log lines are `nightly_tick decision=...`, `nightly_run_started id=... queued_new=... queued_failed=...` and `nightly_run_closed id=... timed_out=...`. They carry no names, paths or text.
- The digest API returns entity names and note paths. These are the same data `/review` already shows to the same authenticated owner.

## 10. Testing

**Unit:**
- `should_start` across:
  - before and after `nightly_at`;
  - DST spring-forward and fall-back days, in Europe/Warsaw;
  - `00:00` and `23:45`;
  - disabled;
  - today's run already present;
  - catch-up at 09:00 after a missed 02:00.
- Settings validation for `SB_NIGHTLY_AT` and `SB_TIMEZONE`.
- The window arithmetic.

**Integration** (Postgres via `just backend::test`):
- Start a run:
  - the cap is shared between new and failed, oldest first;
  - lock hits are not counted;
  - zero queued closes the run at once;
  - with extraction unavailable, the run completes with `unavailable`.
- Two concurrent scheduled starts make one run. A manual start while running returns `busy`.
- A failed start records a `failed` row, and the next tick starts again.
- Closing:
  - close-on-drain;
  - timeout;
  - restart-safe, because the close is stateless.
- Digest queries:
  - proposed items in the output window appear;
  - an accepted or rejected item disappears;
  - items outside the window and owner-made items are excluded;
  - links to rejected entities are excluded;
  - failures count only current revisions;
  - the indexed counts are correct.
- API: 200/404/422/409, history order, and auth.

**Web (Vitest):** the Digest screen in the running, complete, all-caught-up, unavailable, timed-out, failed and no-runs states; the date picker; "Run now" and its 409; polling intervals; the badge; and the landing redirect.

**E2E (fake Ollama):**
1. Reset.
2. Press "Run now" on `/digest`.
3. The NAS and Proxmox items appear without a reload.
4. Accept NAS from `/review`.
5. Back on `/digest`, the To review count is one lower.

## 11. Docs

- **ADR-0014** "Nightly run and live digest": the 15-minute tick over a local-time decision, versus a fixed UTC cron or an asyncio timer, and the live digest versus a frozen snapshot.
- **README:**
  - a "Digest" section: what runs at night, the settings, Run now, `just nightly` and `just nightly-status`;
  - a roadmap row 4b ✅;
  - a screenshot `docs/images/readme/digest.jpg` via `README_SHOTS`.
- **system-design:** mark §4.2 steps 2–5 and 7 as delivered in 4a/4b, and steps 1, 6 and 8 as Phase 5/7; update the §9 4b row.
- **ADR-0003:** the `nightly` queue now exists.
- **ADR-0013 revisit:** answered. The nightly run re-extracts version-bumped notes, capped per night.
- **`.env.example`:** the five settings.

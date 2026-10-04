# Phase 4b Nightly Run and Digest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**
- Run 4a's knowledge-graph extraction every night on its own.
- Show a live "review inbox" digest at `/digest`, which becomes the landing page.

**Architecture:**
- A procrastinate periodic task ticks every 15 minutes. A pure function decides in local time whether today's run should start.
- A run is a row in `nightly_runs`. Starting one queues capped extraction jobs, reusing 4a's per-revision locks. A later tick closes the run once the extract queue drains.
- The digest is computed on read from the run's input and output windows over 4a's tables. Reviewed items drop out on their own.

**Tech Stack:**
- Backend: Python 3.12, FastAPI, psycopg3 async, procrastinate 3.10, `zoneinfo`, dbmate.
- Web: React 19, TanStack Router/Query, openapi-fetch, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-04-phase-4b-nightly-digest-design.md`. The spec wins where this plan differs.

## Global Constraints

**Process:**
- Conventional Commits, headers of 50 characters or fewer, lowercase, imperative.
- **Never** add Co-Authored-By or any AI attribution.
- Commit to `main`. No push and no tags; CI releases v0.8.0.
- Backend tests run via `just backend::test`, which sets TEST_DATABASE_URL. Run commands in the foreground with timeouts.
- Never kill Docker. Never print `.env` values.

**Privacy:**
- Job arguments are ids only.
- Log lines carry counts, ids and codes. They never carry note text, summaries, entity names or paths.

**Settings (exact):**

| Setting | Default | Valid range |
|---|---|---|
| `SB_NIGHTLY_ENABLED` | `true` | — |
| `SB_NIGHTLY_AT` | `"02:00"` | `HH:MM`, 00:00–23:59 |
| `SB_TIMEZONE` | `""` (host zone) | an IANA name, validated with `zoneinfo` |
| `SB_NIGHTLY_MAX_NOTES` | `500` | 1–100000 |
| `SB_NIGHTLY_MAX_HOURS` | `8` | 1–48 |

**Procrastinate:**
- Tick: task name `nightly_tick`, cron `*/15 * * * *`, queue `nightly`, queueing lock `nightly-tick`.
- The `nightly` queue runs in the existing `[ingest, embed]` loop (concurrency 2). There is no third loop.

**Error codes:**
- `nightly_busy` (409).
- Run `error` values: `db_error`, `queue_error`.

**API:**
- Operation ids: `getDigest`, `getDigestByDate`, `listNightlyRuns`, `startNightlyRun`.
- Paths: `GET /api/digest`, `GET /api/digest/{date}`, `GET /api/nightly/runs?limit=`, `POST /api/nightly/run`.

**Copy (verbatim):**

| Case | Text |
|---|---|
| Summary | "Last night: {read} notes read, {failed} failed, {remaining} to review." (note/notes pluralised) |
| Running | "Reading notes: {done} of {queued}." |
| Unavailable | "Extraction is off: no Ollama endpoint is configured (SB_OLLAMA_ENDPOINTS)." |
| Timed out | "Stopped waiting after {hours} hours. Remaining notes will finish in the background." |
| Failed run | "Last night's run failed to start ({error}). It will try again at the next check." |
| Empty To review | "All caught up." |
| Failures hint | "Retried next night, or run `just graph-extract --failed` now." |
| No runs | "No nightly run yet. The first starts at {nightly_at}, or press Run now." |
| Busy | "A run is already in progress." |

**Web polling:** 5 000 ms while the run is `running`, otherwise 60 000 ms.

## Review Focus

1. **The schedule is on in e2e and dev.** With the schedule on, a worker started at 10:00 starts a scheduled run straight away, which is catch-up by design. E2E must set `SB_NIGHTLY_ENABLED=false`, or the graph spec's extraction counts break. Test: Task 7 asserts the e2e env sets it, and Task 3 tests that `tick()` with `enabled=False` never starts a run.
2. **DST days in a configured zone.** On 2026-03-29 in Europe/Warsaw, 02:00–03:00 doesn't exist. A `nightly_at` of `02:30` must still start a run that day, at the first tick at or after 03:00 local, and never twice. Test: in Task 1.
3. **Two workers tick at once.** Exactly one scheduled run must start. Test: in Task 3, two `start_run` calls run concurrently via `asyncio.gather` on separate connections.
4. **A note deleted after it was queued.** The digest's failures list counts only current revisions of live notes, and To review links follow 4a visibility. Test: in Task 4, tombstone a source whose proposed link was created in the window, and assert the link is gone from the digest.
5. **"Run now" pressed twice quickly.** The second press gets 409 `nightly_busy`. The UI shows "A run is already in progress." and doesn't crash. Tests: in Task 5 (API) and Task 6 (UI).

---

## File structure

**Backend** (`backend/src/ai_second_brain/`):
- `nightly/__init__.py`: an empty package marker.
- `nightly/schedule.py`: pure functions. Covers `parse_hhmm`, `local_now`, `should_start`, `run_date_for`. It has no I/O.
- `nightly/store.py`: SQL on `nightly_runs`. Covers insert, previous start, open run, finish and fail.
- `nightly/run.py`: `start_run`, `close_open_run` and `tick`, plus the `RunStart` result.
- `nightly/digest.py`: `digest(conn, run_id)`, `latest_run_id`, `run_id_for_date` and `list_runs`.
- `graph/queries.py` (modify): add `queue_extraction_capped`.
- `config.py` (modify): the five settings and their validators.
- `knowledge/jobs.py` (modify): the `NIGHTLY_QUEUE` constant and the `nightly_tick` periodic task.
- `ingest/worker.py` (modify): the `[ingest, embed]` loop also takes `nightly`.
- `interfaces/api/routes/nightly.py` (new): digest and nightly routes.
- `interfaces/api/schemas.py` (modify): the Digest and NightlyRun models.
- `interfaces/api/app.py` (modify): include the router.
- `interfaces/cli/main.py` (modify): the `nightly run` and `nightly status` commands.

**Migration:**
- `db/migrations/20261004100000_nightly.sql`.
- `db/schema.sql`, regenerated.

**Backend tests:**
- `backend/tests/unit/test_nightly_schedule.py`
- `backend/tests/unit/test_config_nightly.py`
- `backend/tests/integration/test_nightly_run.py`
- `backend/tests/integration/test_nightly_digest.py`
- `backend/tests/integration/test_nightly_api.py`
- `backend/tests/e2e_reset.py` (modify): truncate `nightly_runs`.

**Web:**
- `web/src/features/digest/api.ts`
- `web/src/features/digest/DigestScreen.tsx`
- `web/src/features/digest/copy.ts`
- `web/src/features/digest/*.test.ts(x)`
- `web/src/routes/_app/digest.tsx` (replace).
- `web/src/routes/index.tsx` (redirect to `/digest`).
- `web/src/design-system/AppShell.tsx` (badge).
- `web/src/features/screens/screens.ts` (Digest `phase` and `purpose`).
- `web/src/routes/_app/review.tsx`: invalidate the digest after decisions.
- `web/src/api/openapi.json` and `schema.d.ts`, regenerated.

**E2E:**
- `web/playwright.config.ts`: set `SB_NIGHTLY_ENABLED: "false"`.
- `web/tests/e2e/digest.spec.ts`.
- `web/tests/e2e/readme-screenshots.spec.ts`: add the digest shot.

**Docs:**
- `docs/architecture/adr/0014-nightly-run-and-digest.md`
- `docs/architecture/README.md`: the ADR index.
- README.
- `docs/architecture/system-design.md`.
- ADR-0003.
- ADR-0013.
- `.env.example`.
- `docs/images/readme/digest.jpg`.

---

### Task 1: Settings and the schedule decision

**Files:**
- Create: `backend/src/ai_second_brain/nightly/__init__.py`, `backend/src/ai_second_brain/nightly/schedule.py`
- Modify: `backend/src/ai_second_brain/config.py` (Settings fields, beside `reconcile_minutes`)
- Test: `backend/tests/unit/test_nightly_schedule.py`, `backend/tests/unit/test_config_nightly.py`

**Interfaces:**
- Produces:
  - `parse_hhmm(text: str) -> datetime.time`. Raises `ValueError` on bad input.
  - `resolve_zone(name: str) -> ZoneInfo | tzinfo`. An empty name gives the host zone via `datetime.now().astimezone().tzinfo`.
  - `run_date_for(now_utc: datetime, tz) -> date`.
  - `should_start(now_utc: datetime, tz, nightly_at: time, *, enabled: bool, has_scheduled_run_today: bool) -> bool`.
  - Settings fields: `nightly_enabled: bool`, `nightly_at: str`, `timezone: str`, `nightly_max_notes: int`, `nightly_max_hours: int`.
  - The property `Settings.nightly_zone`, which returns the resolved tzinfo.
  - The property `Settings.nightly_time`, which returns a `time`.

- [ ] **Step 1: Write the failing schedule tests**

```python
# backend/tests/unit/test_nightly_schedule.py
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from ai_second_brain.nightly.schedule import parse_hhmm, run_date_for, should_start

WAW = ZoneInfo("Europe/Warsaw")


def utc(y: int, m: int, d: int, hh: int, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=UTC)


def start(now: datetime, at: str = "02:00", *, enabled: bool = True, done: bool = False) -> bool:
    return should_start(now, WAW, parse_hhmm(at), enabled=enabled, has_scheduled_run_today=done)


@pytest.mark.parametrize(
    ("text", "expected"), [("02:00", time(2, 0)), ("00:00", time(0, 0)), ("23:45", time(23, 45))]
)
def test_parse_hhmm(text: str, expected: time) -> None:
    assert parse_hhmm(text) == expected


@pytest.mark.parametrize("text", ["2:00", "24:00", "12:60", "", "0200", "02:00:00", "ab:cd"])
def test_parse_hhmm_rejects(text: str) -> None:
    with pytest.raises(ValueError):
        parse_hhmm(text)


def test_before_and_after_the_local_time() -> None:
    # 2026-10-04 is CEST (UTC+2): 02:00 local = 00:00 UTC.
    assert not start(utc(2026, 10, 3, 23, 45))  # 01:45 local
    assert start(utc(2026, 10, 4, 0, 0))  # 02:00 local
    assert start(utc(2026, 10, 4, 7, 0))  # 09:00 local: catch-up after a missed 02:00


def test_disabled_or_already_ran() -> None:
    assert not start(utc(2026, 10, 4, 7), enabled=False)
    assert not start(utc(2026, 10, 4, 7), done=True)


def test_spring_forward_gap() -> None:
    # 2026-03-29 Europe/Warsaw: 02:00 -> 03:00. "02:30" does not exist that day.
    assert not start(utc(2026, 3, 29, 0, 45), "02:30")  # 01:45 CET
    assert start(utc(2026, 3, 29, 1, 0), "02:30")  # 03:00 CEST, first tick after the gap


def test_fall_back_repeats_the_hour_once() -> None:
    # 2026-10-25: 03:00 CEST -> 02:00 CET. 02:30 happens twice; one run per date.
    assert start(utc(2026, 10, 25, 0, 30), "02:30")  # first 02:30 (CEST)
    assert not start(utc(2026, 10, 25, 1, 30), "02:30", done=True)  # second 02:30 (CET)


def test_midnight_and_late_times() -> None:
    assert start(utc(2026, 10, 3, 22, 0), "00:00")  # 00:00 local on 10-04
    assert not start(utc(2026, 10, 4, 21, 30), "23:45")  # 23:30 local
    assert start(utc(2026, 10, 4, 21, 45), "23:45")


def test_run_date_is_the_local_date() -> None:
    assert run_date_for(utc(2026, 10, 3, 22, 30), WAW) == date(2026, 10, 4)
    assert run_date_for(utc(2026, 10, 3, 21, 30), WAW) == date(2026, 10, 3)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `just backend::test tests/unit/test_nightly_schedule.py`
Expected: FAIL with `ModuleNotFoundError: ai_second_brain.nightly`.

- [ ] **Step 3: Implement `schedule.py`**

```python
# backend/src/ai_second_brain/nightly/schedule.py
"""When the nightly run starts. Pure functions of the clock; no I/O.

procrastinate evaluates cron in UTC and drops ticks more than 10 minutes late, so the
periodic task only ticks; the local-time decision lives here (spec §5.1).
"""

import re
from datetime import date, datetime, time, tzinfo
from zoneinfo import ZoneInfo

_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def parse_hhmm(text: str) -> time:
    match = _HHMM.match(text)
    if not match:
        raise ValueError("expected HH:MM between 00:00 and 23:59")
    return time(int(match[1]), int(match[2]))


def resolve_zone(name: str) -> tzinfo:
    """An IANA zone, or the host's local zone when empty. Raises on unknown names."""
    if not name:
        local = datetime.now().astimezone().tzinfo
        assert local is not None
        return local
    return ZoneInfo(name)


def run_date_for(now_utc: datetime, tz: tzinfo) -> date:
    return now_utc.astimezone(tz).date()


def should_start(
    now_utc: datetime,
    tz: tzinfo,
    nightly_at: time,
    *,
    enabled: bool,
    has_scheduled_run_today: bool,
) -> bool:
    """True once the local wall clock has reached `nightly_at` today and no run has started.

    Comparing wall-clock times makes DST safe: a nonexistent 02:30 is first reached at 03:00,
    and a repeated 02:30 is blocked by `has_scheduled_run_today`.
    """
    if not enabled or has_scheduled_run_today:
        return False
    return now_utc.astimezone(tz).time() >= nightly_at
```

Also create an empty `backend/src/ai_second_brain/nightly/__init__.py`.

- [ ] **Step 4: Run the schedule tests**

Run: `just backend::test tests/unit/test_nightly_schedule.py`
Expected: PASS.

- [ ] **Step 5: Write the failing config tests**

```python
# backend/tests/unit/test_config_nightly.py
from datetime import time

import pytest
from pydantic import ValidationError

from ai_second_brain.config import Settings


def make(**env: str) -> Settings:
    # Follow the existing config unit tests: build Settings from a minimal valid env.
    from tests.unit.test_config import minimal_settings  # existing helper; adapt if named differently

    return minimal_settings(**env)


def test_defaults() -> None:
    s = make()
    assert s.nightly_enabled is True
    assert s.nightly_time == time(2, 0)
    assert s.nightly_max_notes == 500 and s.nightly_max_hours == 8


def test_valid_values() -> None:
    s = make(SB_NIGHTLY_AT="23:45", SB_TIMEZONE="Europe/Warsaw", SB_NIGHTLY_ENABLED="false")
    assert s.nightly_time == time(23, 45) and s.nightly_enabled is False
    assert str(s.nightly_zone) == "Europe/Warsaw"


@pytest.mark.parametrize(
    "env",
    [
        {"SB_NIGHTLY_AT": "25:00"},
        {"SB_TIMEZONE": "Mars/Base"},
        {"SB_NIGHTLY_MAX_NOTES": "0"},
        {"SB_NIGHTLY_MAX_HOURS": "49"},
    ],
)
def test_invalid_values(env: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        make(**env)
```

The implementer must adapt `make()` to whatever helper the existing `tests/unit/test_config*.py` use to build Settings, for example monkeypatched env plus `Settings(_env_file=None)`. Keep the assertions exactly as written.

- [ ] **Step 6: Add the settings**

In `Settings`, next to `reconcile_minutes`:

```python
    nightly_enabled: bool = True
    nightly_at: str = "02:00"
    timezone: str = ""
    nightly_max_notes: int = Field(default=500, ge=1, le=100_000)
    nightly_max_hours: int = Field(default=8, ge=1, le=48)

    @field_validator("nightly_at")
    @classmethod
    def _valid_nightly_at(cls, value: str) -> str:
        parse_hhmm(value)
        return value

    @field_validator("timezone")
    @classmethod
    def _valid_timezone(cls, value: str) -> str:
        try:
            resolve_zone(value)
        except (ValueError, KeyError, ZoneInfoNotFoundError) as error:
            raise ValueError("unknown IANA time zone") from error
        return value

    @property
    def nightly_time(self) -> time:
        return parse_hhmm(self.nightly_at)

    @property
    def nightly_zone(self) -> tzinfo:
        return resolve_zone(self.timezone)
```

These need the imports `from datetime import time, tzinfo`, `from zoneinfo import ZoneInfoNotFoundError`, and `from ai_second_brain.nightly.schedule import parse_hhmm, resolve_zone`. The env names come from `env_prefix="SB_"`: `SB_NIGHTLY_ENABLED`, `SB_NIGHTLY_AT`, `SB_TIMEZONE`, `SB_NIGHTLY_MAX_NOTES` and `SB_NIGHTLY_MAX_HOURS`.

**Windows note:** `zoneinfo` needs the `tzdata` package on Windows. Check whether `backend/pyproject.toml` already depends on it. If not, add `tzdata` with `uv add --project backend tzdata`, and commit the lockfile in the same commit.

- [ ] **Step 7: Run the tests and the check**

Run: `just backend::test tests/unit/test_nightly_schedule.py tests/unit/test_config_nightly.py`, then `just check`.
Expected: PASS, and the check is clean.

- [ ] **Step 8: Commit**

```bash
git add backend/src/ai_second_brain/nightly backend/src/ai_second_brain/config.py backend/tests/unit/test_nightly_schedule.py backend/tests/unit/test_config_nightly.py backend/pyproject.toml backend/uv.lock
git commit -m "feat(nightly): add schedule settings and decision"
```

---

### Task 2: Migration, run store, and capped queueing

**Files:**
- Create: `db/migrations/20261004100000_nightly.sql`, `backend/src/ai_second_brain/nightly/store.py`
- Modify: `db/schema.sql` (regenerated), `backend/src/ai_second_brain/graph/queries.py`
- Test: `backend/tests/integration/test_nightly_run.py` (store and capped-queue part)

**Interfaces:**
- Consumes: from 4a, `pending_revisions`, `failed_revisions`, `_LIVE` and `JobQueue.extract_revision(revision_id) -> bool` (False on a lock hit).
- Produces:
  - `queue_extraction_capped(conn, queue, version, limit: int) -> tuple[int, int]`. It returns `(queued_new, queued_failed)`, takes pending revisions first, then failed ones, each ordered by `sources.created_at, sources.id`, with the total of candidates capped at `limit`. It commits before deferring.
  - `store.insert_run(conn, *, run_date, trigger) -> UUID | None`. It returns None on a uniqueness conflict, and sets `window_start` from the previous non-failed run.
  - `store.open_run(conn) -> dict | None`.
  - `store.has_scheduled_run(conn, run_date) -> bool`, which counts non-failed scheduled runs.
  - `store.set_counts(conn, run_id, queued_new, queued_failed) -> None`.
  - `store.finish(conn, run_id, *, timed_out=False, unavailable=False) -> None`.
  - `store.fail(conn, run_id, code: str) -> None`.

- [ ] **Step 1: Write the migration**

```sql
-- db/migrations/20261004100000_nightly.sql
-- migrate:up
CREATE TABLE nightly_runs (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_date       date NOT NULL,
  trigger        text NOT NULL CHECK (trigger IN ('schedule','manual')),
  status         text NOT NULL DEFAULT 'running' CHECK (status IN ('running','complete','failed')),
  window_start   timestamptz NOT NULL,
  started_at     timestamptz NOT NULL DEFAULT now(),
  finished_at    timestamptz,
  queued_new     int NOT NULL DEFAULT 0,
  queued_failed  int NOT NULL DEFAULT 0,
  timed_out      boolean NOT NULL DEFAULT false,
  unavailable    boolean NOT NULL DEFAULT false,
  error          text
);
-- One scheduled run per local day that did not fail; manual runs are unlimited.
CREATE UNIQUE INDEX nightly_runs_scheduled_day ON nightly_runs (run_date)
  WHERE trigger = 'schedule' AND status <> 'failed';
-- At most one run open at a time.
CREATE UNIQUE INDEX nightly_runs_one_open ON nightly_runs ((true)) WHERE status = 'running';
CREATE INDEX nightly_runs_started ON nightly_runs (started_at DESC);

-- migrate:down
DROP TABLE nightly_runs;
```

Run `just db::migrate`, then regenerate `db/schema.sql` the way 4a did. Use the db recipe that `just db::schema-check` compares against, e.g. `just db::dump`; check the db justfile for the exact name.

- [ ] **Step 2: Write the failing tests**

```python
# backend/tests/integration/test_nightly_run.py
"""Nightly run store, capped queueing (Task 2) and the run lifecycle (Task 3)."""

from datetime import date
from uuid import UUID

import pytest

from ai_second_brain.graph.prompt import EXTRACTOR_VERSION
from ai_second_brain.graph.queries import queue_extraction_capped
from ai_second_brain.nightly import store

from ..conftest import run_async
from ..ingest_harness import ingest_harness

pytestmark = pytest.mark.integration


class RecordingQueue:
    """JobQueue stand-in: records extract deferrals; ids in `locked` simulate lock hits."""

    def __init__(self, locked: set[UUID] | None = None) -> None:
        self.extracted: list[UUID] = []
        self.locked = locked or set()

    async def extract_revision(self, revision_id: UUID) -> bool:
        if revision_id in self.locked:
            return False
        self.extracted.append(revision_id)
        return True
```

Then add these tests. Each opens `ingest_harness(db_url, vault_with(n notes), None)`, the same way `test_graph_jobs.py` builds its harness, and creates indexed notes with `h.drain()`. Each first runs `TRUNCATE nightly_runs, extractions CASCADE`.

- `test_insert_run_sets_window_from_previous_good_run`:
  1. Insert a manual run. Its `window_start` is `-infinity`.
  2. Finish it, then insert another. The second run's `window_start` equals the first run's `started_at`.
  3. Fail a third run, then insert a fourth. The fourth run's `window_start` still equals the second run's `started_at`.
- `test_one_scheduled_run_per_day_and_one_open`:
  - Inserting `schedule` twice for the same `run_date` makes the second call return None. `has_scheduled_run` is True.
  - While a run is open, inserting a `manual` run also returns None.
  - After `fail()` on the scheduled run, `has_scheduled_run` is False, and a new scheduled insert succeeds.
- `test_capped_queue_new_before_failed_oldest_first`:
  1. Make 4 notes. Mark one as a failed extraction by inserting an `extractions` row with `status='failed'` at `EXTRACTOR_VERSION` for its current revision.
  2. With `limit=2`, the call returns `(2, 0)`, and the queue gets the two oldest pending revisions in `created_at` order.
  3. With `limit=10`, it returns `(3, 1)`. Pending revisions are deferred first, then the failed one.
- `test_capped_queue_lock_hits_not_counted`: put one pending revision in `locked`. With `limit=10`, the result is `(2, 0)` out of 3 pending.

- [ ] **Step 3: Run them to verify they fail**

Run: `just backend::test tests/integration/test_nightly_run.py`
Expected: FAIL on the import errors.

- [ ] **Step 4: Implement `store.py`**

```python
# backend/src/ai_second_brain/nightly/store.py
"""SQL on nightly_runs (spec §4). Callers own commits; each function is one statement."""

from datetime import date
from typing import Any, Literal
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row

Trigger = Literal["schedule", "manual"]


async def insert_run(conn: AsyncConnection, *, run_date: date, trigger: Trigger) -> UUID | None:
    """A new running run, or None when a scheduled run exists for the day or one is open."""
    try:
        async with conn.transaction():
            cur = await conn.execute(
                "INSERT INTO nightly_runs (run_date, trigger, window_start)"
                " VALUES (%s, %s, coalesce((SELECT max(started_at) FROM nightly_runs"
                "  WHERE status <> 'failed'), '-infinity'))"
                " RETURNING id",
                (run_date, trigger),
            )
            row = await cur.fetchone()
    except UniqueViolation:
        return None
    return row[0] if row else None


async def open_run(conn: AsyncConnection) -> dict[str, Any] | None:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT * FROM nightly_runs WHERE status = 'running'")
        return await cur.fetchone()


async def has_scheduled_run(conn: AsyncConnection, run_date: date) -> bool:
    cur = await conn.execute(
        "SELECT EXISTS (SELECT 1 FROM nightly_runs WHERE run_date = %s"
        " AND trigger = 'schedule' AND status <> 'failed')",
        (run_date,),
    )
    row = await cur.fetchone()
    return bool(row and row[0])


async def set_counts(conn: AsyncConnection, run_id: UUID, queued_new: int, queued_failed: int) -> None:
    await conn.execute(
        "UPDATE nightly_runs SET queued_new = %s, queued_failed = %s WHERE id = %s",
        (queued_new, queued_failed, run_id),
    )


async def finish(
    conn: AsyncConnection, run_id: UUID, *, timed_out: bool = False, unavailable: bool = False
) -> None:
    await conn.execute(
        "UPDATE nightly_runs SET status = 'complete', finished_at = now(),"
        " timed_out = %s, unavailable = %s WHERE id = %s AND status = 'running'",
        (timed_out, unavailable, run_id),
    )


async def fail(conn: AsyncConnection, run_id: UUID, code: str) -> None:
    await conn.execute(
        "UPDATE nightly_runs SET status = 'failed', finished_at = now(), error = %s"
        " WHERE id = %s AND status = 'running'",
        (code, run_id),
    )
```

Note on `insert_run`: `max(started_at)` over earlier runs only. The new row's `started_at` is `now()`, and it is not yet visible to its own subquery.

- [ ] **Step 5: Implement `queue_extraction_capped` in `graph/queries.py`**

```python
async def queue_extraction_capped(
    conn: AsyncConnection, queue: JobQueue, version: str, limit: int
) -> tuple[int, int]:
    """Nightly queueing (4b spec §5.2): pending first, then failed, oldest note first, at most
    `limit` candidates together. Returns (queued_new, queued_failed); lock hits are not counted."""
    order = " ORDER BY s.created_at, s.id LIMIT %s"
    cur = await conn.execute(
        "SELECT s.current_revision_id " + _LIVE + " AND e.revision_id IS NULL" + order,
        (version, limit),
    )
    pending = [r[0] for r in await cur.fetchall()]
    cur = await conn.execute(
        "SELECT s.current_revision_id " + _LIVE + " AND e.status = 'failed'" + order,
        (version, limit - len(pending)),
    )
    failed = [r[0] for r in await cur.fetchall()]
    if conn.info.transaction_status != TransactionStatus.IDLE:
        await conn.commit()  # never hold a transaction open while deferring
    counts = []
    for ids in (pending, failed):
        queued = 0
        for revision_id in ids:
            if await queue.extract_revision(revision_id):
                queued += 1
        counts.append(queued)
    logger.info(
        "graph_extract_queued scope=nightly candidates=%d queued_new=%d queued_failed=%d",
        len(pending) + len(failed), counts[0], counts[1],
    )
    return counts[0], counts[1]
```

`LIMIT 0` is valid SQL and returns no rows, so a full first batch needs no special case.

- [ ] **Step 6: Run the tests and the check**

Run: `just backend::test tests/integration/test_nightly_run.py` and `just check`, which includes `db::schema-check`.
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add db/migrations/20261004100000_nightly.sql db/schema.sql backend/src/ai_second_brain/nightly/store.py backend/src/ai_second_brain/graph/queries.py backend/tests/integration/test_nightly_run.py
git commit -m "feat(nightly): add run table and capped queueing"
```

---

### Task 3: Run lifecycle, tick task, and worker wiring

**Files:**
- Create: `backend/src/ai_second_brain/nightly/run.py`
- Modify: `backend/src/ai_second_brain/knowledge/jobs.py`, `backend/src/ai_second_brain/ingest/worker.py`, `backend/tests/ingest_harness.py` (only if its drain list must include `nightly`)
- Test: `backend/tests/integration/test_nightly_run.py` (append)

**Interfaces:**
- Consumes:
  - Task 1: `should_start`, `run_date_for`, and the Settings properties.
  - Task 2: the store functions and `queue_extraction_capped`.
  - 4a: `EXTRACTOR_VERSION`, `EXTRACT_QUEUE`, and `Settings.extract_model_name`.
- Produces:
  - `RunStart = Literal["started", "already_started", "busy", "failed"]`.
  - `@dataclass class StartResult: outcome: RunStart; run_id: UUID | None`.
  - `start_run(pool, queue, settings, trigger, *, now: datetime | None = None) -> StartResult`.
  - `close_open_run(pool, settings, *, now=None) -> UUID | None`. It returns the id of the run it closed, if any.
  - `tick(pool, queue, settings, *, now=None) -> None`.
  - `extract_queue_depth(conn) -> int`. This is the count of `todo` and `doing` extract jobs, factored out of 4a's `graph_status` so both use one query.
  - The procrastinate task `nightly_tick` on queue `nightly`.

- [ ] **Step 1: Write the failing lifecycle tests**

Append to `test_nightly_run.py`, reusing `RecordingQueue`. Build Settings from the harness's `h.ctx.settings`, using `model_copy(update={...})` for the nightly fields and with an extract endpoint configured. For "unavailable", use `ollama_endpoints=[]` and `extract_model=""`. Pass `now=` explicitly as UTC datetimes.

- `test_start_run_queues_and_records_counts`: with 3 pending notes, the outcome is `started`. The row has `queued_new=3`, `queued_failed=0` and `status='running'`.
- `test_start_run_zero_queued_completes`: with nothing pending, the run is `complete`, with `finished_at` set.
- `test_start_run_unavailable_completes_with_flag`: `unavailable=true` and `status='complete'`, and nothing is queued.
- `test_manual_while_running_is_busy`: a second manual start gives `busy`.
- `test_concurrent_scheduled_starts_make_one_run`: run `asyncio.gather(start_run(...schedule...), start_run(...schedule...))`. This needs a pool with at least 2 connections. Exactly one outcome is `started` and the other is `already_started` or `busy`, and there is exactly one row.
- `test_queue_error_marks_failed_and_next_tick_retries`: use a queue whose `extract_revision` raises `RuntimeError`.
  1. The outcome is `failed`. The row has `status='failed'` and `error='queue_error'`.
  2. Then `tick()` with a working queue at a time after `nightly_at` starts a new scheduled run the same `run_date`.
- `test_close_on_drain_and_timeout`:
  1. With a run open and no `procrastinate_jobs` rows for queue `extract` in `todo`/`doing`, `close_open_run` sets `complete`.
  2. Insert a fake `todo` job for queue `extract` using procrastinate's own defer, through `h.queue.extract_revision` on a real revision. The run stays open.
  3. With `now` past `started_at + nightly_max_hours`, the run is closed with `timed_out=true`.
- `test_tick_disabled_never_starts`: a `tick()` with `nightly_enabled=False` at 09:00 local inserts no row.
- `test_tick_starts_once_per_day`: two `tick()` calls at 03:00 and 03:15 local give one scheduled row.

- [ ] **Step 2: Run them to verify they fail**

Run: `just backend::test tests/integration/test_nightly_run.py`
Expected: the new tests FAIL with an ImportError for `ai_second_brain.nightly.run`.

- [ ] **Step 3: Implement `run.py`**

```python
# backend/src/ai_second_brain/nightly/run.py
"""The nightly run lifecycle (spec §5.2, §5.3). Logs carry ids and counts only."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from ai_second_brain.config import Settings
from ai_second_brain.graph.prompt import EXTRACTOR_VERSION
from ai_second_brain.graph.queries import extract_queue_depth, queue_extraction_capped
from ai_second_brain.knowledge.queue import JobQueue
from ai_second_brain.nightly import store
from ai_second_brain.nightly.schedule import run_date_for, should_start

logger = logging.getLogger("ai_second_brain.nightly")

RunStart = Literal["started", "already_started", "busy", "failed"]


@dataclass(frozen=True)
class StartResult:
    outcome: RunStart
    run_id: UUID | None


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


async def start_run(
    pool: AsyncConnectionPool,
    queue: JobQueue,
    settings: Settings,
    trigger: store.Trigger,
    *,
    now: datetime | None = None,
) -> StartResult:
    run_date = run_date_for(_now(now), settings.nightly_zone)
    async with pool.connection() as conn:
        run_id = await store.insert_run(conn, run_date=run_date, trigger=trigger)
        await conn.commit()
        if run_id is None:
            busy = await store.open_run(conn) is not None
            outcome: RunStart = "busy" if busy else "already_started"
            logger.info("nightly_start outcome=%s trigger=%s", outcome, trigger)
            return StartResult(outcome, None)
        try:
            if settings.extract_model_name is None:
                await store.finish(conn, run_id, unavailable=True)
                await conn.commit()
                logger.info("nightly_run_started id=%s unavailable=true", run_id)
                return StartResult("started", run_id)
            queued_new, queued_failed = await queue_extraction_capped(
                conn, queue, EXTRACTOR_VERSION, settings.nightly_max_notes
            )
            await store.set_counts(conn, run_id, queued_new, queued_failed)
            if queued_new + queued_failed == 0:
                await store.finish(conn, run_id)
            await conn.commit()
        except Exception as error:
            await conn.rollback()
            code = "db_error" if isinstance(error, psycopg.Error) else "queue_error"
            await store.fail(conn, run_id, code)
            await conn.commit()
            logger.warning("nightly_run_failed id=%s error=%s", run_id, code)
            return StartResult("failed", run_id)
    logger.info(
        "nightly_run_started id=%s trigger=%s queued_new=%d queued_failed=%d",
        run_id, trigger, queued_new, queued_failed,
    )
    return StartResult("started", run_id)


async def close_open_run(
    pool: AsyncConnectionPool, settings: Settings, *, now: datetime | None = None
) -> UUID | None:
    async with pool.connection() as conn:
        run = await store.open_run(conn)
        if run is None:
            return None
        timed_out = _now(now) - run["started_at"] > timedelta(hours=settings.nightly_max_hours)
        if not timed_out and await extract_queue_depth(conn) > 0:
            return None
        await store.finish(conn, run["id"], timed_out=timed_out)
        await conn.commit()
    logger.info("nightly_run_closed id=%s timed_out=%s", run["id"], str(timed_out).lower())
    return run["id"]


async def tick(
    pool: AsyncConnectionPool, queue: JobQueue, settings: Settings, *, now: datetime | None = None
) -> None:
    current = _now(now)
    await close_open_run(pool, settings, now=current)
    async with pool.connection() as conn:
        today = run_date_for(current, settings.nightly_zone)
        done = await store.has_scheduled_run(conn, today)
    go = should_start(
        current, settings.nightly_zone, settings.nightly_time,
        enabled=settings.nightly_enabled, has_scheduled_run_today=done,
    )
    logger.info("nightly_tick decision=%s", "start" if go else "wait")
    if go:
        await start_run(pool, queue, settings, "schedule", now=current)
```

This needs `import psycopg` at the top of `run.py`.

In `graph/queries.py`, add `extract_queue_depth(conn) -> int`, using the exact SQL from `graph_status`, and have `graph_status` call it.

- [ ] **Step 4: Register the tick task and wire the worker**

In `knowledge/jobs.py`:

```python
NIGHTLY_QUEUE = "nightly"


@blueprint.periodic(cron="*/15 * * * *")
@blueprint.task(name="nightly_tick", queue=NIGHTLY_QUEUE, queueing_lock="nightly-tick", pass_context=True)
async def nightly_tick_task(context: JobContext, timestamp: int) -> None:
    from ai_second_brain.nightly.run import tick

    ctx = _ctx(context)
    await tick(ctx.pool, ctx.queue, ctx.settings)
```

Confirm the decorator order and the `timestamp` parameter against procrastinate 3.10's `Blueprint.periodic` docs. Use context7 or the installed package source. A periodic task receives `timestamp` as its first job argument. If `IngestContext` doesn't expose `settings`/`queue` under these names, use its real attribute names; the graph context builder in `ingest/worker.py` shows them.

In `ingest/worker.py`, `start_job_loops` changes `loop([INGEST_QUEUE, EMBED_QUEUE], 2)` to `loop([INGEST_QUEUE, EMBED_QUEUE, NIGHTLY_QUEUE], 2)`. Update the docstring to name the nightly tick. Extend the existing `start_job_loops` and `run_worker` tests so they expect the `nightly` queue.

- [ ] **Step 5: Run the tests and the check**

Run: `just backend::test` (full suite; ~4 min) and `just check`.
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ai_second_brain/nightly/run.py backend/src/ai_second_brain/graph/queries.py backend/src/ai_second_brain/knowledge/jobs.py backend/src/ai_second_brain/ingest/worker.py backend/tests
git commit -m "feat(nightly): run extraction on a nightly tick"
```

---

### Task 4: Digest queries

**Files:**
- Create: `backend/src/ai_second_brain/nightly/digest.py`
- Test: `backend/tests/integration/test_nightly_digest.py`

**Interfaces:**
- Consumes:
  - the `nightly_runs` rows;
  - 4a's `entities`, `edges`, `extractions`, `sources` and `source_revisions`;
  - 4a's review-visibility rule from `graph/queries.py` `review_links`: no rejected endpoint and a live source. Reuse its SQL fragment if it is factored; otherwise mirror it and cite it.
- Produces:
  - `latest_run_id(conn) -> UUID | None`: the newest by `started_at`.
  - `run_id_for_date(conn, run_date: date) -> UUID | None`: the latest run on that date.
  - `list_runs(conn, limit: int) -> list[dict]`. Keys: `id`, `run_date`, `trigger`, `status`, `started_at`, `remaining`.
  - `digest(conn, run_id: UUID) -> dict | None`. Its shape:

```python
{
  "run": {"id", "run_date", "trigger", "status", "started_at", "finished_at", "queued_new",
          "queued_failed", "timed_out", "unavailable", "error", "done"},
  "review": {
    "entities": {"count": int, "by_type": {type: int}, "top": [{"id", "name", "type", "confidence",
                 "source_title", "source_path"}]},          # top 5 by confidence desc, then name
    "links": {"count": int, "top": [{"id", "subject", "relation", "object", "confidence"}]},
    "remaining": int,                                       # entities.count + links.count
  },
  "failed": {"count": int, "items": [{"path", "error"}]},  # first 10 by path
  "indexed": {"created": int, "changed": int, "deleted": int, "since_beginning": bool},
}
```

**Definitions** (spec §6). `out_end` is `coalesce(finished_at, now())`.
- **To-review entities:** `entities.status='proposed' AND created_at >= started_at AND created_at < out_end`.
  - `source_*` is the note of the entity's earliest mention edge (`relation` in mentions/about from a note). It is NULL if there is none.
- **To-review links:** `edges.status='proposed' AND created_at` in the output window, visible by 4a's review rule, excluding note→entity mention/about edges. This must match what the 4a Links tab lists. Check `review_links` for which relation kinds it shows, and use the same filter.
- **Failed:** `extractions.status='failed' AND attempted_at` in the output window, joined on `sources.current_revision_id = extractions.revision_id AND sources.deleted_at IS NULL`. `path` is `sources.external_ref` and `error` is `extractions.error`. Use the real column names from the migration.
- **Indexed:**
  - `created`: `sources.created_at` in `[window_start, started_at)`.
  - `changed`: `source_revisions.observed_at` in the window, where the source has an older revision.
  - `deleted`: `sources.deleted_at` in the window.
  - `since_beginning`: true when `window_start = '-infinity'`.
- **done:** `extractions.attempted_at >= started_at` for revisions that are current, capped at `queued_new + queued_failed`.

- [ ] **Step 1: Write the failing tests**

Build the state by inserting rows directly: entities, edges and extraction rows with explicit `created_at`/`attempted_at`. Do this inside an `ingest_harness` with 3 indexed notes. Insert a `nightly_runs` row with `started_at = T`, `finished_at = T + 1h` and `window_start = T - 1d`.

The tests:
- `test_review_lists_only_this_runs_proposed_items`: a proposed entity created at `T+10m` shows. One created at `T-1h` (before) and one at `T+2h` (after) don't. Neither does an accepted entity at `T+10m`. Check `by_type` and the top ordering.
- `test_reviewed_items_drop_out`: after `decide.accept_entity` on a listed entity, `count` drops by 1 and `remaining` with it.
- `test_links_follow_review_visibility`: hide a proposed relation edge in the window. First reject one endpoint entity and check it is hidden. Then restore, tombstone its source note, and check it is hidden again. This is Review Focus line 4.
- `test_failed_counts_only_current_live_revisions`: a failed extraction for a current revision shows. One for a superseded revision does not, and neither does one for a tombstoned note.
- `test_indexed_counts`: covers created, changed and deleted in the input window, plus `since_beginning` when `window_start` is `-infinity`.
- `test_latest_and_by_date_and_list`: with two runs on the same date, `run_id_for_date` returns the later one, and `list_runs` is newest first with `remaining`.
- `test_running_run_uses_now_as_window_end`: with `finished_at` NULL, an item created a moment ago is included.

- [ ] **Step 2: Run them to verify they fail**

Run: `just backend::test tests/integration/test_nightly_digest.py`
Expected: FAIL on the ImportError.

- [ ] **Step 3: Implement `digest.py`**

Write each section as one parameterised SQL statement using `dict_row`. Use the definitions above.
- Put the window bounds in a CTE: `WITH r AS (SELECT started_at, coalesce(finished_at, now()) AS out_end, window_start FROM nightly_runs WHERE id = %s)`.
- Return `None` when the run doesn't exist.
- Never log names or paths. A single `logger.debug("digest id=%s", run_id)` is the maximum.

- [ ] **Step 4: Run the tests**

Run: `just backend::test tests/integration/test_nightly_digest.py`, then `just check`.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/ai_second_brain/nightly/digest.py backend/tests/integration/test_nightly_digest.py
git commit -m "feat(nightly): compute the morning digest"
```

---

### Task 5: API, CLI and just recipes

**Files:**
- Create: `backend/src/ai_second_brain/interfaces/api/routes/nightly.py`
- Modify:
  - `interfaces/api/schemas.py`
  - `interfaces/api/app.py` (`include_router`)
  - `interfaces/cli/main.py`
  - the root `justfile`
  - `web/src/api/openapi.json`
  - `web/src/api/schema.d.ts` (regenerated)
- Test: `backend/tests/integration/test_nightly_api.py`, plus CLI tests that follow the existing graph CLI tests

**Interfaces:**
- Consumes: Task 3's `start_run`/`StartResult`, and Task 4's `digest`, `latest_run_id`, `run_id_for_date` and `list_runs`.
- Produces the operation ids and pydantic schema names:
  - `NightlyRun`
  - `DigestReviewEntity`
  - `DigestReviewLink`
  - `Digest`, with `run: NightlyRun | None` and the other sections nullable when `run` is null. It also has `nightly_at: str` (from settings, always present, also when `run` is null) and `nightly_enabled: bool`.
  - `NightlyRunSummary`
  - `NightlyRunList`
  - `NightlyStarted` (`{"run": NightlyRun}`)

**Routes**, on `router = APIRouter(tags=["nightly"], dependencies=[Depends(require_session)])`:
- `GET /digest` → `getDigest`. Returns 200 `Digest`; with no runs, it returns `{"run": null, ...}`.
- `GET /digest/{run_date}` → `getDigestByDate`. `run_date: date` is a path param, so 422 is automatic on a bad date. Returns 404 `{"detail": "not_found"}` when no run exists that day.
- `GET /nightly/runs?limit=30` → `listNightlyRuns`, with `limit: int = Query(30, ge=1, le=365)`.
- `POST /nightly/run` → `startNightlyRun`, with `dependencies=[Depends(require_same_origin)]`.
  - `started` → 202 with the run.
  - `busy` → 409 `nightly_busy`.
  - `failed` → 503 `{"detail": "nightly_failed"}`.
  - If the queue is unavailable, return 503 `database_unavailable`, the same way `graph_extract` does.

**CLI and justfile:**
- `nightly_app = typer.Typer(no_args_is_help=True, help="Nightly run commands.")`, with `nightly run` and `nightly status`.
  - `run` prints "Started a nightly run: queued {n} new and {f} failed notes." It prints "A run is already in progress." with exit code 1 when busy, and "Nightly run failed: {code}" with exit code 1 on failure.
  - `status` prints the summary line from the copy rules, or "No nightly run yet." It never prints names.
- The root `justfile` gets the recipes below, placed beside `graph-status`:

```just
# Start a nightly run now (extraction for new, changed and failed notes)
nightly:
    uv run --project backend ai-second-brain nightly run

# Print the latest nightly run's summary
nightly-status:
    uv run --project backend ai-second-brain nightly status
```

- [ ] **Step 1: Write the failing API tests**

Follow `test_graph_api.py`: use `make_client`, `SAME_ORIGIN`, `EVIL`, `run_async`, and the harness with fake Ollama. The tests:
- `test_digest_empty_returns_null_run`: also asserts `nightly_at == "02:00"` and `nightly_enabled is True`.
- `test_start_run_then_digest`: POST returns 202; GET `/api/digest` returns `run.status` in (`running`, `complete`).
- `test_second_start_while_running_is_409`: needs a run still open. Insert one directly as `running`, then expect 409 with detail `nightly_busy`. This is Review Focus line 5.
- `test_digest_by_date_404_and_422`.
- `test_runs_list_order_and_limit`.
- `test_start_requires_same_origin`: EVIL gives 403.
- `test_routes_require_session`: 401 without a cookie.

- [ ] **Step 2: Run them to verify they fail**

Run: `just backend::test tests/integration/test_nightly_api.py`
Expected: 404 for the routes, so the tests fail.

- [ ] **Step 3: Implement the schemas, routes, wiring, CLI and recipes**

The route's `start_run` call needs the pool, the queue and the settings:
- the pool is `request.app.state.pool`;
- the queue comes from `await request.app.state.ingest.get_queue()`;
- the settings come from `get_settings(request)`.

Map the `digest()` dict straight onto the response models.

- [ ] **Step 4: Regenerate the API client**

Run `just api-client`. Check `git diff --stat web/src/api`: it should show only additions for the new paths.

- [ ] **Step 5: Run the tests and the check**

Run: `just backend::test` and `just check`. The check includes `api-client-check`.
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ai_second_brain/interfaces backend/tests/integration/test_nightly_api.py justfile web/src/api
git commit -m "feat(api): expose the digest and nightly runs"
```

---

### Task 6: Digest screen, badge and landing

**Files:**
- Create: `web/src/features/digest/api.ts`, `web/src/features/digest/copy.ts`, `web/src/features/digest/DigestScreen.tsx`, `web/src/features/digest/api.test.ts`, `web/src/features/digest/copy.test.ts`, `web/src/features/digest/DigestScreen.test.tsx`
- Modify:
  - `web/src/routes/_app/digest.tsx`: render `DigestScreen` with `validateSearch` for `?date=YYYY-MM-DD`.
  - `web/src/routes/index.tsx`: redirect to `/digest`.
  - `web/src/design-system/AppShell.tsx`: the badge.
  - `web/src/design-system/AppShell.test.tsx`.
  - `web/src/features/screens/screens.ts`: Digest `phase: "4b"`, with purpose "What last night's run found and what still needs your decision."
  - `web/src/routes/_app/review.tsx`: invalidate `digestKeys.all` after each successful decision.
- Test: the files above.

**Interfaces:**
- Consumes: the Task 5 operation ids through `api` from `@/api/client`, and `HttpError`/`detailOf` from `@/features/sources/api`.
- Produces:
  - `digestKeys = { all: ["digest"], latest: ["digest","latest"], byDate: (d) => ["digest", d], runs: ["digest","runs"] }`.
  - `DIGEST_POLL_FAST_MS = 5_000` and `DIGEST_POLL_SLOW_MS = 60_000`.
  - `digestPollInterval(data) -> number`: fast iff `data?.run?.status === "running"`.
  - `digestQuery(date?: string)`.
  - `nightlyRunsQuery`.
  - `useStartNightlyRun()`, a mutation. On success it invalidates `digestKeys.all`. On 409 it rejects with `HttpError(409)`, and the screen shows the busy copy.
  - From `copy.ts`: `summaryLine(d)`, `runningLine(d)`, `notesWord(n)`, and the constants for every copy string in Global Constraints.

**Screen layout and behaviour** (spec §8):
- Heading "Digest", with the run date as a subtitle.
- A date picker: a `<select>` labelled "Run date", with options from `nightlyRunsQuery`.
- A "Run now" button. It is disabled while `run.status === "running"` or the mutation is pending. A 409 shows the busy copy in a `role="status"` line.
- A summary line, or one of the running, unavailable, timed-out or failed-run lines. These sit in an `aria-live="polite"` region.
- **"To review" section:**
  - `<h2>` with the remaining count.
  - Per-type counts.
  - The top entities, each linking to `/entities/$entityId`.
  - The top links as "subject — relation label — object", using 4a's `RELATION_LABEL` from `@/features/graph/labels`.
  - "Review all" goes to `/review`, and "Review links" goes to `/review?tab=links`. Check how ReviewScreen selects its tab and use that.
  - "All caught up." when remaining is 0.
- **"Failed" section:** shown only when the count is above 0. It lists paths in `<code>` with the failures hint.
- **"Indexed" line:** "{created} added, {changed} changed, {deleted} deleted since the previous run". When `since_beginning`, the line ends "since the beginning" instead.
- **No runs:** the no-runs copy fills `{nightly_at}` from `Digest.nightly_at`, which Task 5 returns.
- **Badge:** `NavLinks` reads `digestQuery()` (the latest) via `useQuery`. When `remaining > 0`, it renders `<span className="ml-auto rounded-full bg-accent px-1.5 text-xs text-accent-fg">{n}<span className="sr-only"> to review</span></span>` beside the Digest label only. The badge must not break the phone bar layout.
- **Polling:** `refetchInterval: (q) => digestPollInterval(q.state.data)`.

- [ ] **Step 1: Write the failing unit tests**

`api.test.ts`:
- `digestPollInterval` returns fast for running and slow for complete, failed and undefined.
- Starting a run invalidates `digestKeys.all`. Use a real QueryClient with `invalidateQueries` spied.

`copy.test.ts`:
- `summaryLine` pluralisation: "1 note read", "2 notes read".
- The exact strings from Global Constraints.

`DigestScreen.test.tsx`: mock `api.GET`/`api.POST` the way the graph screen tests do, and cover:
- the no-runs state;
- running with the "Reading notes: 3 of 10." line;
- complete with items;
- all caught up;
- unavailable;
- timed out;
- a failed run;
- "Run now" posting, and a 409 showing "A run is already in progress." (Review Focus line 5);
- the date picker switching runs;
- the entity link href.

`AppShell.test.tsx`:
- a badge with "3" and the screen-reader text " to review" when remaining is 3;
- no badge when 0.

Add a router test: `/` redirects to `/digest`. Follow the existing `projects.test.ts` redirect pattern.

- [ ] **Step 2: Run them to verify they fail**

Run: `pnpm --dir web exec vitest run src/features/digest src/design-system src/routes`
Expected: FAIL.

- [ ] **Step 3: Implement**

Build it with the shared components in `web/src/design-system/ui` and the Tailwind tokens. Follow `EntitiesScreen.tsx` for the section structure, loading and error states. Error copy follows the existing pattern: "Couldn't load the digest. Try again." with a retry button.

- [ ] **Step 4: Run the tests and the check**

Run: `pnpm --dir web exec vitest run` and `just check`.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src
git commit -m "feat(web): add the digest screen and badge"
```

---

### Task 7: End-to-end

**Files:**
- Modify: `web/playwright.config.ts` (add `SB_NIGHTLY_ENABLED: "false"` to `serverEnv`), `backend/tests/e2e_reset.py` (truncate `nightly_runs`)
- Create: `web/tests/e2e/digest.spec.ts`

**Interfaces:**
- Consumes:
  - the fake Ollama replies from `web/tests/e2e/fixtures/fake-ollama.ts`, which are matched on `Note path:` (the NAS and Proxmox replies);
  - the reset helper used by `graph.spec.ts`;
  - the `expect.poll` readiness wait on `/api/graph/status` with `revisions.total >= 5`.

- [ ] **Step 1: Write the spec**

```ts
// web/tests/e2e/digest.spec.ts
import { expect, test } from "@playwright/test";
// Reuse the login and reset helpers exactly as graph.spec.ts imports them.

test("run now fills the digest and review empties it", async ({ page }) => {
  test.setTimeout(150_000); // extraction via fake Ollama runs through the worker
  // 1. reset + login (as graph.spec.ts)
  // 2. wait until the fixture vault is indexed:
  //    await expect.poll(async () => (await (await page.request.get("/api/graph/status")).json()).revisions.total, { timeout: 60_000 }).toBeGreaterThanOrEqual(5);
  await page.goto("/");
  await expect(page).toHaveURL(/\/digest$/);
  await expect(page.getByText(/No nightly run yet/)).toBeVisible();
  await page.getByRole("button", { name: "Run now" }).click();
  const review = page.getByRole("region", { name: /To review/ });
  await expect(review.getByRole("link", { name: "NAS", exact: true })).toBeVisible({ timeout: 90_000 });
  await expect(review.getByRole("link", { name: "Proxmox", exact: true })).toBeVisible();
  const before = Number(await review.getByTestId("remaining").textContent());
  await page.goto("/review");
  await page.getByRole("article", { name: "NAS" }).getByRole("button", { name: /accept/i }).click();
  await page.goto("/digest");
  await expect(review.getByTestId("remaining")).toHaveText(String(before - 1));
});
```

The implementer adjusts the selectors to what Task 6 renders:
- the To review `<section aria-labelledby>`, so it has the region role;
- a `data-testid="remaining"` on the count;
- the real Accept button name on review cards.

No sleeps.

- [ ] **Step 2: Update the config and reset**

Add `SB_NIGHTLY_ENABLED: "false"` to `serverEnv` in `web/playwright.config.ts`, which covers Review Focus line 1. Add `nightly_runs` to the TRUNCATE list in `backend/tests/e2e_reset.py`.

- [ ] **Step 3: Run e2e twice**

Run `just e2e` twice.
Expected: both runs pass. Expect 17 passed plus the opt-in skips.

- [ ] **Step 4: Commit**

```bash
git add web/playwright.config.ts backend/tests/e2e_reset.py web/tests/e2e/digest.spec.ts
git commit -m "test(e2e): run the nightly digest end to end"
```

---

### Task 8: Docs, ADR and screenshot

**Files:**
- Create: `docs/architecture/adr/0014-nightly-run-and-digest.md`, `docs/images/readme/digest.jpg`
- Modify:
  - `docs/architecture/README.md` (the ADR index)
  - `README.md`
  - `docs/architecture/system-design.md` (§4.2, §9)
  - `docs/architecture/adr/0003-postgres-job-queue.md`
  - `docs/architecture/adr/0013-knowledge-graph-review.md` (the revisit line)
  - `.env.example`
  - `web/tests/e2e/readme-screenshots.spec.ts`
  - the spec header status, set to "approved, implemented"

**Content requirements:**

**ADR-0014:**
- Follow the ADR-0012/0013 format.
- **Context:** procrastinate cron runs in UTC and skips late ticks.
- **Decision:** a 15-minute tick plus the local-time `should_start`, a run row, and a live digest.
- **Options considered:** a fixed UTC cron, an asyncio timer like reconcile, and a frozen snapshot at 06:00.
- **Consequences:**
  - The digest empties as the owner reviews.
  - A hand-started extraction during a run keeps the run open (the spec §5.3 limitation).
  - The schedule must be off in e2e.

**README:**
- A "Digest" section:
  - what runs at night;
  - the five settings, as a table with their defaults;
  - Run now, `just nightly` and `just nightly-status`;
  - that `/` now opens the Digest.
- Roadmap: 4b ✅, and the next phase as it is listed in system-design §9.
- The screenshot.

**system-design:**
- In §4.2, tag the steps:
  - steps 2–5 and 7: "(4a/4b)";
  - steps 1 and 8: "(Phase 5)";
  - step 6: "(Phase 7)".
- §9: mark the 4b row delivered.

**ADR-0003:** the `nightly` queue exists and runs in the ingest/embed loop.

**ADR-0013:** answer the revisit line. The nightly run re-extracts version-bumped notes, capped per night.

**`.env.example`:** the five settings, commented, with their defaults.

**Screenshot:**
- Add a test gated by `README_SHOTS` at 1280×800, following the existing ones. It resets, waits for indexing, presses Run now, waits for the To review items, then shoots `docs/images/readme/digest.jpg`.
- Run it from `web/` in PowerShell: `$env:README_SHOTS='1'; pnpm exec playwright test readme-screenshots`.
- Read the image to check it.

- [ ] **Step 1: Write the docs and the screenshot test, and generate the image**
- [ ] **Step 2: Verify every documented name against the code**

Check the env names, defaults and recipes with:

```bash
grep -n "nightly" justfile backend/src/ai_second_brain/config.py
```

- [ ] **Step 3: Run the final checks**

Run `just check`, `just test` and `just e2e`.
Expected: all green.

- [ ] **Step 4: Commit, in three commits**

```bash
git add docs/architecture/adr/0014-nightly-run-and-digest.md docs/architecture/README.md
git commit -m "docs(adr): record the nightly run and digest"
git add web/tests/e2e/readme-screenshots.spec.ts docs/images/readme/digest.jpg
git commit -m "test(e2e): add the digest screenshot"
git add README.md docs .env.example
git commit -m "docs: document the nightly run and digest"
```

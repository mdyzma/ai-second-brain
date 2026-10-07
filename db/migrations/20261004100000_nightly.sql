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

-- migrate:up
-- When a worker started working on the run. A manual run is created by the API before any
-- worker has it, so "started" alone can't tell a queued scan from a running one.
ALTER TABLE ingest_runs ADD COLUMN picked_up_at timestamptz;

-- migrate:down
ALTER TABLE ingest_runs DROP COLUMN picked_up_at;

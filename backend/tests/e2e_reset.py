"""Empty the ingestion tables of the e2e database (run just before the e2e worker starts)."""

import os

import psycopg

with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
    conn.execute("TRUNCATE sources, ingest_runs, procrastinate_jobs CASCADE")

print("e2e database reset", flush=True)

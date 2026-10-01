"""Empty the ingestion tables of the e2e database (run just before the e2e worker starts)."""

import os
import shutil
from pathlib import Path

import psycopg

with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
    conn.execute("TRUNCATE sources, ingest_runs, procrastinate_jobs CASCADE")

vault = os.environ.get("SB_VAULT_PATH")
if vault:
    shutil.rmtree(Path(vault) / os.environ.get("SB_CAPTURE_DIR", "Inbox"), ignore_errors=True)

print("e2e database reset", flush=True)

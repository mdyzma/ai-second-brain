"""Empty the ingestion tables of the e2e database (run just before the e2e worker starts).

It also removes the fixture vault's Inbox/ left by capture tests. The folder name is fixed
(never read from the environment), and the delete is refused unless the target is a real
directory strictly inside the e2e fixture vault.
"""

import os
import shutil
from pathlib import Path

FIXTURE_VAULT_TAIL = ("web", "tests", "e2e", "fixtures", "vault")
CAPTURE_DIR = "Inbox"


def clear_capture_dir(vault_path: str) -> bool:
    """Delete <fixture vault>/Inbox. Returns False (and warns) when it is not safe to."""
    vault = Path(vault_path).resolve()
    if vault.parts[-len(FIXTURE_VAULT_TAIL) :] != FIXTURE_VAULT_TAIL:
        print("e2e reset: SB_VAULT_PATH is not the fixture vault; Inbox not cleared", flush=True)
        return False
    target = vault / CAPTURE_DIR
    if not target.exists() and not target.is_symlink():
        return True
    if target.is_symlink() or target.is_junction() or not target.is_dir():
        print("e2e reset: Inbox is not a real directory; not cleared", flush=True)
        return False
    resolved = target.resolve()
    if resolved.parent != vault or resolved == vault:
        print("e2e reset: Inbox resolves outside the fixture vault; not cleared", flush=True)
        return False
    shutil.rmtree(resolved)
    return True


def main() -> None:
    import psycopg

    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        conn.execute("TRUNCATE sources, ingest_runs, procrastinate_jobs CASCADE")

    vault = os.environ.get("SB_VAULT_PATH")
    if vault:
        clear_capture_dir(vault)

    print("e2e database reset", flush=True)


if __name__ == "__main__":
    main()

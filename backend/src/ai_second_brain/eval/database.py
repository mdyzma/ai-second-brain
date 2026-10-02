"""Prepare the scratch evaluation database with dbmate: core schema, then the eval-only cache."""

import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

from psycopg import AsyncConnection

from ai_second_brain.eval.queries import EvalConfigError

DBMATE_TIMEOUT_S = 300


class DbmateError(EvalConfigError):
    """dbmate failed. `output` holds its stdout/stderr for the CLI to print (never logged)."""

    def __init__(self, errors: list[str], output: str = "") -> None:
        super().__init__(errors)
        self.output = output


def dbmate_base(root: Path) -> list[str]:
    configured = os.environ.get("DBMATE", "").strip()
    if configured:
        return shlex.split(configured)
    pnpm = shutil.which("pnpm")  # pnpm.cmd on Windows
    if pnpm is None:
        raise EvalConfigError(["pnpm not found; install it or set DBMATE to a dbmate binary"])
    return [pnpm, "--dir", str(root), "exec", "dbmate"]


def prepare(url: str, root: Path) -> None:
    """Migrate the scratch DB: the normal migrations, then db/eval with its own table."""
    base = [*dbmate_base(root), "--url", url, "--no-dump-schema"]
    runs = [
        [*base, "--migrations-dir", str(root / "db" / "migrations"), "up"],
        [
            *base,
            "--migrations-dir",
            str(root / "db" / "eval" / "migrations"),
            "--migrations-table",
            "schema_migrations_eval",
            "up",
        ],
    ]
    for command in runs:
        try:
            result = subprocess.run(  # noqa: S603 - argument list, never a shell
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=DBMATE_TIMEOUT_S,
            )
        except FileNotFoundError:
            raise EvalConfigError(
                ["dbmate could not be started; install it or set DBMATE to a dbmate binary"]
            ) from None
        except subprocess.TimeoutExpired:
            raise EvalConfigError(
                [f"dbmate did not finish within {DBMATE_TIMEOUT_S} s; is PostgreSQL running?"]
            ) from None
        if result.returncode != 0:
            output = (result.stdout or "") + (result.stderr or "")
            raise DbmateError(
                [f"dbmate failed (exit {result.returncode}); see its output above"], output
            )


async def check_ready(conn: AsyncConnection[Any]) -> None:
    async with conn.transaction():  # never leave an implicit transaction open
        cur = await conn.execute("SELECT to_regclass('public.eval_embedding_cache') IS NOT NULL")
        row = await cur.fetchone()
    if not row or not row[0]:
        raise EvalConfigError(["the evaluation database is not prepared: run just eval-prepare"])

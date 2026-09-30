"""Integration harness: everything lives on the loop of one run_async() call."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, LiteralString

from procrastinate import App
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from ai_second_brain.chat.providers.base import ChatTimeouts
from ai_second_brain.chat.providers.ollama import create_http_client
from ai_second_brain.config import Settings
from ai_second_brain.knowledge.context import IngestContext
from ai_second_brain.knowledge.embedder import Embedder
from ai_second_brain.knowledge.jobs import EMBED_QUEUE, INGEST_QUEUE, create_job_app
from ai_second_brain.knowledge.queue import ProcrastinateQueue
from ai_second_brain.vault.paths import Vault

from .conftest import TEST_HASH

FAST = ChatTimeouts(connect=1.0, read=1.0, probe=0.5)
TRUNCATE_ALL: LiteralString = (
    "TRUNCATE sources, ingest_runs, procrastinate_jobs, procrastinate_events,"
    " procrastinate_periodic_defers, procrastinate_workers CASCADE"
)


@dataclass
class Harness:
    ctx: IngestContext
    app: App
    pool: AsyncConnectionPool

    async def drain(self) -> None:
        await self.app.run_worker_async(
            queues=[INGEST_QUEUE, EMBED_QUEUE],
            wait=False,
            concurrency=1,
            install_signal_handlers=False,
            listen_notify=False,
            additional_context={"ingest": self.ctx},
        )

    async def rows(self, sql: LiteralString, *params: Any) -> list[dict[str, Any]]:
        async with self.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return await cur.fetchall() if cur.description is not None else []


@asynccontextmanager
async def ingest_harness(
    db_url: str, vault_root: Path | None, embed_url: str | None, **overrides: Any
) -> AsyncIterator[Harness]:
    values: dict[str, Any] = {
        "DATABASE_URL": db_url,
        "owner_password_hash": TEST_HASH,
        "vault_path": str(vault_root) if vault_root else None,
        "embed_url_override": embed_url or "",
    }
    values.update(overrides)
    settings = Settings(_env_file=None, **values)  # pyright: ignore[reportCallIssue]
    async with AsyncConnectionPool[AsyncConnection](
        db_url, min_size=1, max_size=4, open=False
    ) as pool:
        async with pool.connection() as conn:
            await conn.execute(TRUNCATE_ALL)
        app = create_job_app(db_url)
        async with app.open_async(), create_http_client() as client:
            embedder = Embedder(embed_url, "bge-m3", 1024, client, FAST) if embed_url else None
            vault = Vault(vault_root, settings.vault_excludes) if vault_root else None
            ctx = IngestContext(
                pool, settings, vault, embedder, ProcrastinateQueue(app), 1, "bge-m3", 1024
            )
            yield Harness(ctx, app, pool)

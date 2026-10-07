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
from ai_second_brain.config import OllamaEndpointConfig, Settings
from ai_second_brain.graph.context import GraphContext
from ai_second_brain.graph.llm import ExtractClient
from ai_second_brain.knowledge.context import IngestContext
from ai_second_brain.knowledge.embedder import Embedder
from ai_second_brain.knowledge.jobs import (
    EMBED_QUEUE,
    EXTRACT_QUEUE,
    INGEST_QUEUE,
    create_job_app,
)
from ai_second_brain.knowledge.queue import ProcrastinateQueue
from ai_second_brain.search.embedding import QueryEmbedder
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
    graph: GraphContext | None = None  # set by `extract_url`; also puts `extract` in drain()

    async def drain(self) -> None:
        queues = [INGEST_QUEUE, EMBED_QUEUE]
        context: dict[str, Any] = {"ingest": self.ctx}
        if self.graph is not None:
            queues.append(EXTRACT_QUEUE)
            context["graph"] = self.graph
        await self.app.run_worker_async(
            queues=queues,
            wait=False,
            concurrency=1,
            install_signal_handlers=False,
            listen_notify=False,
            additional_context=context,
        )

    async def rows(self, sql: LiteralString, *params: Any) -> list[dict[str, Any]]:
        async with self.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return await cur.fetchall() if cur.description is not None else []


@asynccontextmanager
async def ingest_harness(
    db_url: str,
    vault_root: Path | None,
    embed_url: str | None,
    *,
    fresh: bool = True,
    extract_url: str | None = None,
    **overrides: Any,
) -> AsyncIterator[Harness]:
    """`fresh=False` keeps the database as it is (e.g. an API-created run row).
    `extract_url` adds a graph context (fake chat model at that URL) and the `extract` queue."""
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
        if fresh:
            async with pool.connection() as conn:
                await conn.execute(TRUNCATE_ALL)
        app = create_job_app(db_url)
        # Every run_worker_async (drain() too) starts procrastinate's periodic deferrer, which
        # would defer a `nightly_tick` job right away if a quarter hour passed in the last 10
        # minutes. Tests drive `tick()` directly, so the harness never schedules it.
        app.periodic_registry.periodic_tasks.clear()
        async with app.open_async(), create_http_client() as client:
            embedder = Embedder(embed_url, "bge-m3", 1024, client, FAST) if embed_url else None
            vault = Vault(vault_root, settings.vault_excludes) if vault_root else None
            ctx = IngestContext(
                pool, settings, vault, embedder, ProcrastinateQueue(app), 1, "bge-m3", 1024
            )
            graph = None
            if extract_url is not None:
                endpoint = OllamaEndpointConfig(label="t", url=extract_url, model="fake")
                extract_client = ExtractClient(client, [endpoint], "fake", FAST, 8192)
                graph = GraphContext(
                    pool, settings, extract_client, QueryEmbedder(embedder), ctx.queue
                )
            yield Harness(ctx, app, pool, graph)

"""Admin CLI: `ai-second-brain serve | openapi | hash-password | chat-smoke`."""

import asyncio
import copy
import json
import logging.config
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

import typer
import uvicorn
from pydantic import ValidationError
from uvicorn.config import LOGGING_CONFIG

from ai_second_brain.auth.passwords import hash_password
from ai_second_brain.chat.events import ErrorEvent, ReceiptEvent, TokenEvent
from ai_second_brain.chat.models import ChatMode
from ai_second_brain.chat.providers.base import ChatTimeouts
from ai_second_brain.chat.providers.ollama import OllamaPool, create_http_client
from ai_second_brain.chat.repository import InMemoryChatRepository
from ai_second_brain.chat.retrieval import NullRetriever, Retriever
from ai_second_brain.chat.service import ChatService
from ai_second_brain.config import Settings, get_settings
from ai_second_brain.db import create_pool
from ai_second_brain.interfaces.api.app import openapi_schema
from ai_second_brain.knowledge import status as read_status
from ai_second_brain.knowledge import store
from ai_second_brain.knowledge.context import IngestContext
from ai_second_brain.knowledge.embedder import Embedder
from ai_second_brain.knowledge.jobs import create_job_app
from ai_second_brain.knowledge.queue import ProcrastinateQueue
from ai_second_brain.runtime import new_event_loop
from ai_second_brain.search.embedding import QueryEmbedder
from ai_second_brain.search.retriever import HybridRetriever
from ai_second_brain.vault.paths import Vault

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Second Brain admin CLI.")

SRC_DIR = Path(__file__).resolve().parents[2]


def build_log_config() -> dict[str, Any]:
    """uvicorn's default logging plus the app's own loggers at INFO on stderr."""
    config = copy.deepcopy(LOGGING_CONFIG)
    config["loggers"]["ai_second_brain"] = {
        "handlers": ["default"],
        "level": "INFO",
        "propagate": False,
    }
    return config


@app.command()
def serve(
    reload: Annotated[bool, typer.Option(help="Restart on code changes (dev).")] = False,
    port: Annotated[int | None, typer.Option(help="Port (default: SB_API_PORT).")] = None,
) -> None:
    """Run the API on 127.0.0.1."""
    try:
        settings = get_settings()
    except ValidationError as error:
        typer.echo(f"Configuration error:\n{error}", err=True)
        raise typer.Exit(code=1) from error
    uvicorn.run(
        "ai_second_brain.interfaces.api.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=port or settings.api_port,
        reload=reload,
        reload_dirs=[str(SRC_DIR)] if reload else None,
        loop="ai_second_brain.runtime:new_event_loop",
        access_log=False,
        log_config=build_log_config(),
    )


@app.command()
def openapi(
    output: Annotated[
        Path | None, typer.Option(help="Write to this file instead of stdout.")
    ] = None,
) -> None:
    """Print or write the OpenAPI schema (deterministic: sorted keys, LF endings)."""
    text = json.dumps(openapi_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if output is None:
        typer.echo(text, nl=False)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8", newline="\n")


@app.command("hash-password")
def hash_password_command() -> None:
    """Hash the owner password and print the .env line (nothing is written to disk)."""
    password: str = typer.prompt("Password", hide_input=True, confirmation_prompt=True)
    typer.echo(f"SB_OWNER_PASSWORD_HASH='{hash_password(password)}'")


SMOKE_QUESTION = "Reply with the single word: ready"


async def _chat_smoke(settings: Any) -> int:
    async with create_http_client() as client:
        pool = OllamaPool(
            settings.ollama_endpoints,
            client,
            timeouts=ChatTimeouts(),
            max_tokens=settings.chat_max_tokens,
            num_ctx=settings.chat_num_ctx,
            status_ttl=0,
        )
        for status in await pool.status():
            state = "reachable" if status.reachable else "UNREACHABLE"
            degraded = " (degraded)" if status.degraded else ""
            typer.echo(f"{status.label:<16} {status.model:<28} {state}{degraded}")
        repository = InMemoryChatRepository()  # nothing is saved
        db_pool = None
        retriever: Retriever = NullRetriever()
        if settings.vault_path is not None:
            db_pool = create_pool(settings.database_url)
            await db_pool.open(wait=False)  # a down DB surfaces as retrieval_error
            embedder = (
                Embedder(settings.embed_url, settings.embed_model, 1024, client, ChatTimeouts())
                if settings.embed_url
                else None
            )
            retriever = HybridRetriever(db_pool, QueryEmbedder(embedder), settings)
        try:
            return await _smoke_turn(
                ChatService(repository, retriever, pool, cloud=None), repository
            )
        finally:
            if db_pool is not None:
                await db_pool.close()


async def _smoke_turn(service: ChatService, repository: InMemoryChatRepository) -> int:
    session = await repository.create_session(ChatMode.PRIVATE)
    answer: list[str] = []
    exit_code = 1
    async for event in service.run_turn(session, SMOKE_QUESTION):
        if isinstance(event, TokenEvent):
            answer.append(event.text)
        elif isinstance(event, ReceiptEvent):
            exit_code = 0
            typer.echo(f"Answered by {event.endpoint} ({event.model}) in {event.duration_ms} ms")
        elif isinstance(event, ErrorEvent):
            typer.echo(f"Error [{event.component}] {event.code}: {event.message}")
    if exit_code == 0:
        typer.echo(f"Answer: {''.join(answer).strip()}")
    return exit_code


@app.command("chat-smoke")
def chat_smoke() -> None:
    """Probe each Ollama endpoint and get one private answer (nothing is saved)."""
    try:
        settings = get_settings()
    except ValidationError as error:
        typer.echo(f"Configuration error:\n{error}", err=True)
        raise typer.Exit(code=1) from error
    if not settings.ollama_endpoints:
        typer.echo("No Ollama endpoints configured. Set SB_OLLAMA_ENDPOINTS in .env (see README).")
        raise typer.Exit(code=1)
    code = asyncio.run(_chat_smoke(settings), loop_factory=new_event_loop)
    raise typer.Exit(code=code)


@app.command()
def worker() -> None:
    """Run the ingestion worker (jobs + vault watcher + reconcile). Ctrl+C to stop."""
    from ai_second_brain.ingest.worker import run_worker

    try:
        settings = get_settings()
    except ValidationError as error:
        typer.echo(f"Configuration error:\n{error}", err=True)
        raise typer.Exit(code=1) from error
    logging.config.dictConfig(build_log_config())
    code = asyncio.run(run_worker(settings), loop_factory=new_event_loop)
    raise typer.Exit(code=code)


vault_app = typer.Typer(no_args_is_help=True, help="Vault ingestion commands.")
app.add_typer(vault_app, name="vault")


def _load_settings() -> Settings:
    try:
        return get_settings()
    except ValidationError as error:
        typer.echo(f"Configuration error:\n{error}", err=True)
        raise typer.Exit(code=1) from error


@asynccontextmanager
async def _cli_context(settings: Settings) -> AsyncIterator[IngestContext]:
    """The worker's IngestContext, for one-off commands (jobs it queues run in the worker)."""
    pool = create_pool(settings.database_url)
    await pool.open(wait=True, timeout=30)
    try:
        async with pool.connection() as conn:
            space_id, model, dims = await store.default_space(conn)
        job_app = create_job_app(settings.database_url)
        async with job_app.open_async(), create_http_client() as client:
            embedder = (
                Embedder(settings.embed_url, settings.embed_model, dims, client, ChatTimeouts())
                if settings.embed_url
                else None
            )
            vault = (
                Vault(settings.vault_path, settings.vault_excludes) if settings.vault_path else None
            )
            yield IngestContext(
                pool, settings, vault, embedder, ProcrastinateQueue(job_app), space_id, model, dims
            )
    finally:
        await pool.close()


async def _vault_reconcile(settings: Settings, allow_mass_delete: bool) -> int:
    from ai_second_brain.vault.reconcile import reconcile

    async with _cli_context(settings) as ctx:
        outcome, counts = await reconcile(ctx, trigger="cli", allow_mass_delete=allow_mass_delete)
    typer.echo(f"outcome: {outcome}")
    for name, value in counts.as_dict().items():
        typer.echo(f"{name}: {value}")
    return 0 if outcome == "ok" else 1


@vault_app.command("reconcile")
def vault_reconcile(
    allow_mass_delete: Annotated[
        bool, typer.Option("--allow-mass-delete", help="Override the mass-delete guard.")
    ] = False,
) -> None:
    """One reconcile pass in this process (jobs it queues run in the worker)."""
    settings = _load_settings()
    if settings.vault_path is None:
        typer.echo("No vault configured. Set SB_VAULT_PATH in .env.")
        raise typer.Exit(code=1)
    logging.config.dictConfig(build_log_config())
    try:
        code = asyncio.run(
            _vault_reconcile(settings, allow_mass_delete), loop_factory=new_event_loop
        )
    except Exception as error:  # the run is recorded; keep the message free of paths and content
        typer.echo(f"Reconcile failed: {type(error).__name__}")
        raise typer.Exit(code=1) from error
    raise typer.Exit(code=code)


def _flatten(prefix: str, value: Any) -> list[tuple[str, Any]]:
    if isinstance(value, dict):
        return [
            item for k, v in value.items() for item in _flatten(f"{prefix}.{k}" if prefix else k, v)
        ]
    return [(prefix, value)]


async def _vault_status(settings: Settings) -> list[tuple[str, Any]]:
    pool = create_pool(settings.database_url)
    await pool.open(wait=True, timeout=30)
    try:
        async with pool.connection() as conn:
            summary = await read_status.summary(conn, settings, 1, None)
    finally:
        await pool.close()
    return _flatten("", summary)


@vault_app.command("status")
def vault_status() -> None:
    """Print the ingestion summary."""
    settings = _load_settings()
    try:
        rows = asyncio.run(_vault_status(settings), loop_factory=new_event_loop)
    except Exception as error:
        typer.echo(f"Status unavailable: {type(error).__name__}")
        raise typer.Exit(code=1) from error
    width = max(len(key) for key, _ in rows)
    for key, value in rows:
        typer.echo(f"{key + ':':<{width + 1}} {value}")

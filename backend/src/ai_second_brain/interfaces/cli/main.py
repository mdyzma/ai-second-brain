"""Admin CLI: `ai-second-brain serve | openapi | hash-password | chat-smoke | vault | eval`."""

import asyncio
import copy
import json
import logging.config
import os
import sys
import tempfile
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal, LiteralString

import typer
import uvicorn
import yaml
from psycopg import AsyncConnection
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
from ai_second_brain.config import REPO_ROOT, Settings, eval_model_tags, get_settings
from ai_second_brain.db import create_pool
from ai_second_brain.eval.database import DbmateError, EvalDatabaseError
from ai_second_brain.eval.database import prepare as prepare_eval_db
from ai_second_brain.eval.embedding import ModelEmbedError, PreflightError
from ai_second_brain.eval.guards import check_eval_url
from ai_second_brain.eval.queries import EvalConfigError, parse_queries
from ai_second_brain.eval.report import SUMMARY_HEADER, summary_rows, write_report
from ai_second_brain.eval.runner import RunResult, run_eval
from ai_second_brain.eval.snapshot import read_only_transaction
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


eval_app = typer.Typer(no_args_is_help=True, help="Embedding evaluation commands.")
app.add_typer(eval_app, name="eval")

SUGGEST_SQL: LiteralString = (
    "SELECT external_ref FROM ("
    " SELECT s.external_ref,"
    "  row_number() OVER (PARTITION BY"
    "   CASE WHEN strpos(s.external_ref, '/') > 0 THEN split_part(s.external_ref, '/', 1)"
    "   ELSE '' END ORDER BY random()) AS pick,"
    "  CASE WHEN strpos(s.external_ref, '/') > 0 THEN split_part(s.external_ref, '/', 1)"
    "  ELSE '' END AS folder"
    " FROM sources s WHERE s.deleted_at IS NULL AND s.current_revision_id IS NOT NULL"
    ") sampled ORDER BY pick, folder LIMIT %s"
)


def utf8_stream(stream: object) -> None:
    """Make a console stream UTF-8 (errors replaced): a cp1250 pipe must not kill a long run."""
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="replace")


@eval_app.callback()
def eval_callback() -> None:
    """Embedding evaluation commands."""
    utf8_stream(sys.stdout)
    utf8_stream(sys.stderr)


def _eval_errors(error: EvalConfigError) -> None:
    """Config errors name query ids and paths (owner's terminal only), never query text."""
    if isinstance(error, DbmateError) and error.output:
        typer.echo(error.output.rstrip(), err=True)
    for line in error.errors:
        typer.echo(line, err=True)


async def _dev_read(settings: Settings, sql_text: LiteralString, *params: Any) -> list[Any]:
    """Run one read inside a read-only transaction on the dev database."""
    async with await AsyncConnection.connect(settings.database_url) as conn:
        async with read_only_transaction(conn):
            cur = await conn.execute(sql_text, params or None)
            return [row[0] for row in await cur.fetchall()]


async def _suggest_paths(settings: Settings, n: int) -> list[str]:
    """Live notes, round-robin across top-level folders (each folder shuffled)."""
    return await _dev_read(settings, SUGGEST_SQL, n)


async def _dev_live_paths(settings: Settings) -> set[str]:
    return set(
        await _dev_read(
            settings,
            "SELECT s.external_ref FROM sources s"
            " WHERE s.deleted_at IS NULL AND s.current_revision_id IS NOT NULL",
        )
    )


@eval_app.command("prepare")
def eval_prepare() -> None:
    """Create and migrate the scratch evaluation database (SB_EVAL_DATABASE_URL)."""
    settings = _load_settings()
    try:
        check_eval_url(
            settings.eval_database_url, settings.database_url, os.environ.get("TEST_DATABASE_URL")
        )
        prepare_eval_db(settings.eval_database_url, REPO_ROOT)
    except EvalConfigError as error:
        _eval_errors(error)
        raise typer.Exit(code=1) from error
    typer.echo("Evaluation database ready.")


@eval_app.command("suggest")
def eval_suggest(
    n: Annotated[int, typer.Option("--n", min=1, max=1000, help="How many notes to sample.")] = 60,
    out: Annotated[
        Path | None,
        typer.Option(
            "--out",
            help="Write UTF-8 to this new file (e.g. ~/.second-brain/eval/queries.yaml)"
            " instead of stdout; an existing file is never overwritten.",
        ),
    ] = None,
) -> None:
    """Draft a starter queries.yaml (write a question for each entry).

    Recommended: just eval-suggest --out ~/.second-brain/eval/queries.yaml
    (a PowerShell `>` redirect writes UTF-16, which the loader rejects).
    """
    settings = _load_settings()
    target = out.expanduser() if out else None
    if target is not None and target.exists():
        typer.echo(f"{target} already exists; not overwriting it.", err=True)
        raise typer.Exit(code=1)
    try:
        paths = asyncio.run(_suggest_paths(settings, n), loop_factory=new_event_loop)
    except Exception as error:
        typer.echo(f"Suggest failed ({type(error).__name__}).", err=True)
        raise typer.Exit(code=2) from error
    queries = [
        {"id": f"q{i:02d}", "q": "", "lang": "pl", "kind": "topic", "targets": [path]}
        for i, path in enumerate(paths, start=1)
    ]
    text = yaml.safe_dump({"version": 1, "queries": queries}, allow_unicode=True, sort_keys=False)
    if target is None:
        typer.echo(text.rstrip())
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8", newline="\n") as handle:  # "x": never overwrite
            handle.write(text)
    except FileExistsError as error:
        typer.echo(f"{target} already exists; not overwriting it.", err=True)
        raise typer.Exit(code=1) from error
    except OSError as error:
        typer.echo(f"Could not write {target} ({type(error).__name__}).", err=True)
        raise typer.Exit(code=2) from error
    typer.echo(f"Wrote {len(queries)} entries to {target}; write a question for each.")


@eval_app.command("check")
def eval_check(
    queries: Annotated[
        Path | None, typer.Option("--queries", help="Queries file (default: SB_EVAL_QUERIES).")
    ] = None,
) -> None:
    """Validate the query set and its targets against the current index."""
    settings = _load_settings()
    try:
        loaded, errors = parse_queries(queries or settings.eval_queries_path)
        live = asyncio.run(_dev_live_paths(settings), loop_factory=new_event_loop)
        errors += [
            f"{q.id}: target not in the index: {target}"
            for q in loaded
            for target in q.targets
            if target not in live
        ]
        if errors:
            raise EvalConfigError(errors)
    except EvalConfigError as error:
        _eval_errors(error)
        raise typer.Exit(code=1) from error
    except Exception as error:
        typer.echo(f"Check failed ({type(error).__name__}).", err=True)
        raise typer.Exit(code=2) from error
    typer.echo(f"queries: {len(loaded)} (all targets are in the index)")
    for key in ("lang", "kind"):
        counts = Counter(getattr(q, key) for q in loaded)
        typer.echo(f"by {key}: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))


async def _eval_run(settings: Settings, queries_path: Path, models: list[str]) -> RunResult:
    async with create_http_client() as client:
        return await run_eval(
            settings,
            queries_path=queries_path,
            models=models,
            dev_url=settings.database_url,
            eval_url=settings.eval_database_url,
            test_url=os.environ.get("TEST_DATABASE_URL"),
            client=client,
            progress=typer.echo,
        )


RESUME_HINT = "Cached vectors are kept: run again to resume."
UNREACHABLE = {
    "dev": "Could not reach the dev database (DATABASE_URL).",
    "eval": "Could not reach the evaluation database (SB_EVAL_DATABASE_URL).",
}


def _save_report(result: RunResult, out_dir: Path, now: datetime) -> Path:
    """Write the report; if out_dir fails, keep the (possibly hours-long) run in the temp dir."""
    try:
        return write_report(result, out_dir, now)
    except OSError as error:
        typer.echo(
            f"Warning: could not write the report to {out_dir} ({type(error).__name__});"
            " writing it to the temp directory instead.",
            err=True,
        )
    try:
        # mkdtemp: a fresh folder only the owner can read (0700), since results.json names notes
        fallback = Path(tempfile.mkdtemp(prefix="sb-eval-", dir=tempfile.gettempdir()))
        return write_report(result, fallback, now)
    except OSError as error:
        typer.echo(f"Evaluation failed ({type(error).__name__}).", err=True)
        raise typer.Exit(code=2) from error


@eval_app.command("run")
def eval_run(
    models: Annotated[
        str | None,
        typer.Option("--models", help="Comma-separated tags; the first is the incumbent."),
    ] = None,
    out: Annotated[
        Path | None, typer.Option("--out", help="Report directory (default: SB_EVAL_DIR).")
    ] = None,
    queries: Annotated[
        Path | None, typer.Option("--queries", help="Queries file (default: SB_EVAL_QUERIES).")
    ] = None,
) -> None:
    """Run the embedding bake-off and write report.md + results.json."""
    settings = _load_settings()
    try:
        model_list = (
            eval_model_tags(models, settings.embed_model) if models else settings.eval_model_list
        )
    except ValueError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error
    out_dir = out.expanduser().resolve() if out else settings.eval_report_dir
    if out_dir == REPO_ROOT or REPO_ROOT in out_dir.parents:
        typer.echo("--out must be outside the repository", err=True)
        raise typer.Exit(code=1)
    logging.config.dictConfig(build_log_config())
    try:
        result = asyncio.run(
            _eval_run(settings, queries or settings.eval_queries_path, model_list),
            loop_factory=new_event_loop,
        )
    except KeyboardInterrupt as error:
        typer.echo(f"Interrupted. {RESUME_HINT}", err=True)
        raise typer.Exit(code=130) from error
    except EvalConfigError as error:
        _eval_errors(error)
        raise typer.Exit(code=1) from error
    except PreflightError as error:
        if error.code == "embed_model_missing":
            typer.echo(
                f"Model {error.model} is not installed: run ollama pull {error.model}", err=True
            )
        else:
            typer.echo(f"Preflight failed: {error.code} ({error.model})", err=True)
        raise typer.Exit(code=1) from error
    except ModelEmbedError as error:
        typer.echo(f"Embedding failed ({error.code}) for {error.model}. {RESUME_HINT}", err=True)
        raise typer.Exit(code=2) from error
    except EvalDatabaseError as error:
        typer.echo(UNREACHABLE[error.which], err=True)
        raise typer.Exit(code=2) from error
    except Exception as error:
        typer.echo(f"Evaluation failed ({type(error).__name__}).", err=True)
        raise typer.Exit(code=2) from error
    folder = _save_report(result, out_dir, datetime.now())
    typer.echo(result.verdict.line)
    rows = summary_rows(result)
    widths = [max(len(r[i]) for r in [SUMMARY_HEADER, *rows]) for i in range(len(SUMMARY_HEADER))]
    for row in [SUMMARY_HEADER, *rows]:
        typer.echo("  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)).rstrip())
    typer.echo(f"Report: {folder}")


graph_app = typer.Typer(no_args_is_help=True, help="Knowledge graph commands.")
app.add_typer(graph_app, name="graph")


async def _graph_extract(settings: Settings, scope: Literal["new", "failed"]) -> int:
    from ai_second_brain.graph.prompt import EXTRACTOR_VERSION
    from ai_second_brain.graph.queries import queue_extraction

    pool = create_pool(settings.database_url)
    await pool.open(wait=True, timeout=30)
    try:
        job_app = create_job_app(settings.database_url)
        async with job_app.open_async(), pool.connection() as conn:
            return await queue_extraction(
                conn, ProcrastinateQueue(job_app), EXTRACTOR_VERSION, scope
            )
    finally:
        await pool.close()


@graph_app.command("extract")
def graph_extract(
    failed: Annotated[
        bool, typer.Option("--failed", help="Retry notes whose extraction failed.")
    ] = False,
) -> None:
    """Queue knowledge-graph extraction (the worker runs the jobs)."""
    settings = _load_settings()
    if settings.extract_model_name is None:
        typer.echo("No local model is configured for extraction (SB_OLLAMA_ENDPOINTS).", err=True)
        raise typer.Exit(code=1)
    logging.config.dictConfig(build_log_config())
    try:
        queued = asyncio.run(
            _graph_extract(settings, "failed" if failed else "new"), loop_factory=new_event_loop
        )
    except Exception as error:
        typer.echo(f"Queueing failed: {type(error).__name__}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"Queued {queued} {'note' if queued == 1 else 'notes'} for extraction.")


async def _graph_status(settings: Settings) -> list[tuple[str, Any]]:
    from ai_second_brain.graph.prompt import EXTRACTOR_VERSION
    from ai_second_brain.graph.queries import graph_status

    pool = create_pool(settings.database_url)
    await pool.open(wait=True, timeout=30)
    try:
        async with pool.connection() as conn:
            summary = await graph_status(conn, EXTRACTOR_VERSION)
    finally:
        await pool.close()
    return [("model", settings.extract_model_name or "none"), *_flatten("", summary)]


@graph_app.command("status")
def graph_status_command() -> None:
    """Print extraction progress and entity counts (never entity names)."""
    settings = _load_settings()
    try:
        rows = asyncio.run(_graph_status(settings), loop_factory=new_event_loop)
    except Exception as error:
        typer.echo(f"Status unavailable: {type(error).__name__}", err=True)
        raise typer.Exit(code=1) from error
    width = max(len(key) for key, _ in rows)
    for key, value in rows:
        typer.echo(f"{key + ':':<{width + 1}} {value}")

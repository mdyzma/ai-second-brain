"""Admin CLI: `ai-second-brain serve | openapi | hash-password | chat-smoke`."""

import asyncio
import copy
import json
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
from ai_second_brain.chat.retrieval import NullRetriever
from ai_second_brain.chat.service import ChatService
from ai_second_brain.config import get_settings
from ai_second_brain.interfaces.api.app import openapi_schema
from ai_second_brain.runtime import new_event_loop

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
            status_ttl=0,
        )
        for status in await pool.status():
            state = "reachable" if status.reachable else "UNREACHABLE"
            degraded = " (degraded)" if status.degraded else ""
            typer.echo(f"{status.label:<16} {status.model:<28} {state}{degraded}")
        repository = InMemoryChatRepository()  # nothing is saved
        service = ChatService(repository, NullRetriever(), pool, cloud=None)
        session = await repository.create_session(ChatMode.PRIVATE)
        answer: list[str] = []
        exit_code = 1
        async for event in service.run_turn(session, SMOKE_QUESTION):
            if isinstance(event, TokenEvent):
                answer.append(event.text)
            elif isinstance(event, ReceiptEvent):
                exit_code = 0
                typer.echo(
                    f"Answered by {event.endpoint} ({event.model}) in {event.duration_ms} ms"
                )
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

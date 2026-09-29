"""Admin CLI: `ai-second-brain serve | openapi | hash-password`."""

import copy
import json
from pathlib import Path
from typing import Annotated, Any

import typer
import uvicorn
from pydantic import ValidationError
from uvicorn.config import LOGGING_CONFIG

from ai_second_brain.auth.passwords import hash_password
from ai_second_brain.config import get_settings
from ai_second_brain.interfaces.api.app import openapi_schema

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

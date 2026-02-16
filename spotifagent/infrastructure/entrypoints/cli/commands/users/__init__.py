import asyncio
import uuid

import typer

from spotifagent.infrastructure.entrypoints.cli.commands.users.create import user_create_logic
from spotifagent.infrastructure.entrypoints.cli.commands.users.update import user_update_logic
from spotifagent.infrastructure.entrypoints.cli.parsers import parse_email
from spotifagent.infrastructure.entrypoints.cli.parsers import parse_password

app = typer.Typer()


@app.command("create")
def create(  # pragma: no cover
    email: str = typer.Option(..., help="User email address", parser=parse_email),
    password: str = typer.Option(..., prompt=True, hide_input=True, confirmation_prompt=True, parser=parse_password),
) -> None:
    try:
        asyncio.run(user_create_logic(email, password))
    except Exception as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e


@app.command("update")
def update(  # pragma: no cover
    user_id: uuid.UUID = typer.Argument(..., help="User ID to update"),
    email: str | None = typer.Option(None, help="User email address to change", parser=parse_email),
    password: str | None = typer.Option(None, help="User password to change", parser=parse_password),
) -> None:
    try:
        asyncio.run(user_update_logic(user_id, email=email, password=password))
    except Exception as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e

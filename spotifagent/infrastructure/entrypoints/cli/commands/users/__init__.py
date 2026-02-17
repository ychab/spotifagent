import asyncio
import uuid

from pydantic import ValidationError

import typer

from spotifagent.domain.entities.users import UserUpdate
from spotifagent.domain.exceptions import UserAlreadyExistsException
from spotifagent.domain.exceptions import UserNotFound
from spotifagent.infrastructure.entrypoints.cli.commands.users.create import user_create_logic
from spotifagent.infrastructure.entrypoints.cli.commands.users.update import user_update_logic
from spotifagent.infrastructure.entrypoints.cli.parsers import parse_email
from spotifagent.infrastructure.entrypoints.cli.parsers import parse_password

app = typer.Typer()


@app.command("create")
def create(
    email: str = typer.Option(..., help="User email address", parser=parse_email),
    password: str = typer.Option(..., prompt=True, hide_input=True, confirmation_prompt=True, parser=parse_password),
) -> None:
    try:
        asyncio.run(user_create_logic(email, password))
    except UserAlreadyExistsException as e:
        typer.secho(f"User with email {email} already exists.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e
    except Exception as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e

    typer.secho(f"User {email} created successfully!", fg=typer.colors.GREEN)


@app.command("update")
def update(
    user_id: uuid.UUID = typer.Argument(..., help="User ID to update"),
    email: str | None = typer.Option(None, help="User email address to change", parser=parse_email),
    password: str | None = typer.Option(None, help="User password to change", parser=parse_password),
) -> None:
    # Set only explicit values to update.
    attributes = {k: v for k, v in {"email": email, "password": password}.items() if v is not None}
    try:
        user_data = UserUpdate(**attributes)
    except ValidationError as e:
        raise typer.BadParameter(str(e)) from e

    try:
        asyncio.run(user_update_logic(user_id, user_data=user_data))
    except UserNotFound as e:
        typer.secho(f"User not found with ID {user_id}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e
    except Exception as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e

    typer.secho(f"User {user_id} updated successfully!", fg=typer.colors.GREEN)

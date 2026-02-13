from typing import cast

import typer

from spotifagent import __version__
from spotifagent.infrastructure.config.loggers import configure_loggers
from spotifagent.infrastructure.config.settings.app import app_settings
from spotifagent.infrastructure.entrypoints.cli.commands import spotify
from spotifagent.infrastructure.entrypoints.cli.commands import users
from spotifagent.infrastructure.entrypoints.cli.parsers import parse_log_handlers
from spotifagent.infrastructure.types import LogHandler
from spotifagent.infrastructure.types import LogLevel

app = typer.Typer(
    name="Spotifagent",
    help="CLI for Spotifagent application.",
    no_args_is_help=True,
)

app.add_typer(users.app, name="users", help="User management commands")
app.add_typer(spotify.app, name="spotify", help="Spotify interaction commands")


def version_callback(show_version: bool) -> None:
    if show_version:
        typer.echo(f"Spotifagent Version: {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    log_level: LogLevel = typer.Option(
        app_settings.LOG_LEVEL,
        "--log-level",
        "-l",
        case_sensitive=False,
        help="Set the logging level.",
    ),
    log_handlers: list[str] = typer.Option(
        ["cli", "cli_alert"],
        "--log-handler",
        case_sensitive=True,
        callback=parse_log_handlers,
        help="Set the logging handlers.",
    ),
    version: bool | None = typer.Option(
        None,
        "--version",
        "-v",
        help="Show the application's version and exit.",
        callback=version_callback,
        is_eager=True,
    ),
):
    configure_loggers(level=log_level, handlers=cast(list[LogHandler], log_handlers))

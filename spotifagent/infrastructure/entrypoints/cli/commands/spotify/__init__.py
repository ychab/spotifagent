import asyncio
import time

import typer
from rich.console import Console
from rich.table import Table

from spotifagent.application.services.spotify import TimeRange
from spotifagent.application.use_cases.spotify_sync import SyncConfig
from spotifagent.domain.exceptions import UserNotFound
from spotifagent.infrastructure.entrypoints.cli.commands.spotify.connect import connect_logic
from spotifagent.infrastructure.entrypoints.cli.commands.spotify.sync import sync_logic
from spotifagent.infrastructure.entrypoints.cli.parsers import parse_email

console = Console()
app = typer.Typer()


@app.command("connect", help="Connect a user account to Spotify via OAuth.")
def connect(
    email: str = typer.Option(..., help="User email address", parser=parse_email),
    timeout: float = typer.Option(60.0, help="Seconds to wait for authentication.", min=10),
    poll_interval: float = typer.Option(2.0, help="Seconds between status checks.", min=0.5),
) -> None:
    """
    Initiates the Spotify OAuth flow for a specific user.

    Important: the app must be run and being able to receive the Spotify's callback
    define with the setting SPOTIFY_REDIRECT_URI.
    """
    try:
        asyncio.run(connect_logic(email, timeout, poll_interval))
    except UserNotFound as e:
        raise typer.BadParameter(f"User not found with email: {email}") from e
    except TimeoutError as e:
        typer.secho(
            f"\n\nUnable to connect after {timeout} seconds. Did you open your browser and accept?",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1) from e
    except Exception as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e

    typer.secho("\n\nAuthentication successful! \u2705", fg=typer.colors.GREEN)


@app.command("sync", help="Synchronize the Spotify user's items.")
def sync(
    email: str = typer.Option(..., help="User email address", parser=parse_email),
    purge: bool = typer.Option(
        False,
        "--purge/--no-purge",
        help="Whether to purge all user's items",
    ),
    purge_artist_top: bool = typer.Option(
        False,
        "--purge-artist-top/--no-purge-artist-top",
        help="Whether to purge user's top artists",
    ),
    purge_track_top: bool = typer.Option(
        False,
        "--purge-track-top/--no-purge-track-top",
        help="Whether to purge user's top tracks",
    ),
    purge_track_saved: bool = typer.Option(
        False,
        "--purge-track-saved/--no-purge-track-saved",
        help="Whether to purge user's saved tracks",
    ),
    purge_track_playlist: bool = typer.Option(
        False,
        "--purge-track-playlist/--no-purge-track-playlist",
        help="Whether to purge user's playlist tracks",
    ),
    sync: bool = typer.Option(
        False,
        "--sync/--no-sync",
        help="Whether to sync all user's items",
    ),
    sync_artist_top: bool = typer.Option(
        False,
        "--sync-artist-top/--no-sync-artist-top",
        help="Whether to sync user's top artists",
    ),
    sync_track_top: bool = typer.Option(
        False,
        "--sync-track-top/--no-sync-track-top",
        help="Whether to sync user's top tracks",
    ),
    sync_track_saved: bool = typer.Option(
        False,
        "--sync-track-saved/--no-sync-track-saved",
        help="Whether to sync user's saved tracks",
    ),
    sync_track_playlist: bool = typer.Option(
        False,
        "--sync-track-playlist/--no-sync-track-playlist",
        help="Whether to sync user's playlist tracks",
    ),
    page_limit: int = typer.Option(
        50,
        "--page-limit",
        help="How many items to fetch per page",
        min=1,
        max=50,
    ),
    time_range: TimeRange = typer.Option(
        "long_term",
        "--time-range",
        help="The time range of the items to fetch (top artist and top tracks)",
    ),
    batch_size: int = typer.Option(
        300,
        "--batch-size",
        help="The number of items to bulk upsert in DB",
        min=1,
        max=500,
    ),
) -> None:
    """
    Synchronize the Spotify user's items into the database, including artists and tracks.
    """
    start_time = time.perf_counter()

    config = SyncConfig(
        purge=purge,
        purge_artist_top=purge_artist_top,
        purge_track_top=purge_track_top,
        purge_track_saved=purge_track_saved,
        purge_track_playlist=purge_track_playlist,
        sync=sync,
        sync_artist_top=sync_artist_top,
        sync_track_top=sync_track_top,
        sync_track_saved=sync_track_saved,
        sync_track_playlist=sync_track_playlist,
        page_limit=page_limit,
        time_range=time_range,
        batch_size=batch_size,
    )
    if not config.has_purge() and not config.has_sync():
        typer.secho("At least one flag must be provided.", fg=typer.colors.RED, err=True)
        raise typer.Abort()

    try:
        report = asyncio.run(sync_logic(email=email, config=config))
    except UserNotFound as e:
        raise typer.BadParameter(f"User not found with email: {email}") from e
    except Exception as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e

    if report.has_errors:
        for error in report.errors:
            typer.secho(error, fg=typer.colors.RED, err=True)
        raise typer.Abort()

    end_time = time.perf_counter()
    duration = end_time - start_time

    typer.secho(f"\nSynchronization successful in {duration:.2f}s!\n", fg=typer.colors.GREEN)

    table = Table(title="Sync Results")
    table.add_column("Label", style="cyan")
    table.add_column("Value", justify="right", style="magenta")

    table.add_row("Artists purged", str(report.purge_artist))
    table.add_row("Artists created", str(report.artist_created))
    table.add_row("Artists updated", str(report.artist_updated))
    table.add_row("Tracks purged", str(report.purge_track))
    table.add_row("Tracks created", str(report.track_created))
    table.add_row("Tracks updated", str(report.track_updated))

    console.print(table)

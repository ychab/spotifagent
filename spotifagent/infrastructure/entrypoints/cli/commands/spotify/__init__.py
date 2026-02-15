import asyncio

import typer

from spotifagent.application.services.spotify import TimeRange
from spotifagent.infrastructure.entrypoints.cli.commands.spotify.connect import connect_logic
from spotifagent.infrastructure.entrypoints.cli.commands.spotify.sync import sync_logic
from spotifagent.infrastructure.entrypoints.cli.parsers import parse_email

app = typer.Typer()


@app.command("connect", help="Connect a user account to Spotify via OAuth.")
def connect(  # pragma: no cover
    email: str = typer.Option(..., help="User email address", parser=parse_email),
    timeout: float = typer.Option(60.0, help="Seconds to wait for authentication.", min=10),
    poll_interval: float = typer.Option(2.0, help="Seconds between status checks.", min=0.5),
):
    """
    Initiates the Spotify OAuth flow for a specific user.

    Important: the app must be run and being able to receive the Spotify's callback
    define with the setting SPOTIFY_REDIRECT_URI.
    """
    try:
        asyncio.run(connect_logic(email, timeout, poll_interval))
    except Exception as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e


@app.command("sync", help="Synchronize the Spotify user's items.")
def sync(  # pragma: no cover
    email: str = typer.Option(..., help="User email address", parser=parse_email),
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
    sync_artist_top: bool = typer.Option(
        True,
        "--sync-artist-top/--no-sync-artist-top",
        help="Whether to sync user's top artists",
    ),
    sync_track_top: bool = typer.Option(
        True,
        "--sync-track-top/--no-sync-track-top",
        help="Whether to sync user's top tracks",
    ),
    sync_track_saved: bool = typer.Option(
        True,
        "--sync-track-saved/--no-sync-track-saved",
        help="Whether to sync user's saved tracks",
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
):
    """
    Synchronize the Spotify user's items into the database, including artists and tracks.
    """
    try:
        asyncio.run(
            sync_logic(
                email=email,
                purge_artist_top=purge_artist_top,
                purge_track_top=purge_track_top,
                purge_track_saved=purge_track_saved,
                sync_artist_top=sync_artist_top,
                sync_track_top=sync_track_top,
                sync_track_saved=sync_track_saved,
                page_limit=page_limit,
                time_range=time_range,
                batch_size=batch_size,
            )
        )
    except Exception as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e

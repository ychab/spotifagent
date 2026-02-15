from contextlib import AsyncExitStack

from pydantic import EmailStr

import typer

from spotifagent.application.services.spotify import TimeRange
from spotifagent.application.use_cases.spotify_sync import spotify_sync
from spotifagent.infrastructure.entrypoints.cli.dependencies import get_artist_repository
from spotifagent.infrastructure.entrypoints.cli.dependencies import get_db
from spotifagent.infrastructure.entrypoints.cli.dependencies import get_spotify_client
from spotifagent.infrastructure.entrypoints.cli.dependencies import get_spotify_user_session_factory
from spotifagent.infrastructure.entrypoints.cli.dependencies import get_track_repository
from spotifagent.infrastructure.entrypoints.cli.dependencies import get_user_repository


async def sync_logic(
    email: EmailStr,
    purge_artist_top: bool = False,
    purge_track_top: bool = False,
    purge_track_saved: bool = False,
    sync_artist_top: bool = False,
    sync_track_top: bool = False,
    sync_track_saved: bool = False,
    page_limit: int = 50,
    time_range: TimeRange = "long_term",
    batch_size: int = 300,
) -> None:
    if not any(
        [purge_artist_top, purge_track_top, purge_track_saved, sync_artist_top, sync_track_top, sync_track_saved]
    ):
        typer.secho("At least one flag must be provided.", fg=typer.colors.RED, err=True)
        raise typer.Abort()

    async with AsyncExitStack() as stack:
        session = await stack.enter_async_context(get_db())

        spotify_client = await stack.enter_async_context(get_spotify_client())
        spotify_session_factory = get_spotify_user_session_factory(
            session=session,
            spotify_client=spotify_client,
        )

        user_repository = get_user_repository(session)
        artist_repository = get_artist_repository(session)
        track_repository = get_track_repository(session)

        user = await user_repository.get_by_email(email)
        if user is None:
            raise typer.BadParameter(f"User not found with email: {email}")

        report = await spotify_sync(
            user=user,
            spotify_session_factory=spotify_session_factory,
            artist_repository=artist_repository,
            track_repository=track_repository,
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

        if report.has_errors:
            for error in report.errors:
                typer.secho(error, fg=typer.colors.RED, err=True)
            raise typer.Abort()

        typer.secho("\nSynchronization successful!\n", fg=typer.colors.GREEN)

        if purge_artist_top:
            typer.secho(f"- {report.purge_artist} artists purged", fg=typer.colors.GREEN)
        if purge_track_top or purge_track_saved:
            typer.secho(f"- {report.purge_track} tracks purged", fg=typer.colors.GREEN)

        if sync_artist_top:
            typer.secho(f"- {report.artist_created} artists created", fg=typer.colors.GREEN)
            typer.secho(f"- {report.artist_updated} artists updated", fg=typer.colors.GREEN)
        if sync_track_top or sync_track_saved:
            typer.secho(f"- {report.track_created} tracks created", fg=typer.colors.GREEN)
            typer.secho(f"- {report.track_updated} tracks updated", fg=typer.colors.GREEN)

from contextlib import AsyncExitStack

from pydantic import EmailStr

from spotifagent.application.use_cases.spotify_sync import SyncConfig
from spotifagent.application.use_cases.spotify_sync import SyncReport
from spotifagent.application.use_cases.spotify_sync import spotify_sync
from spotifagent.domain.exceptions import UserNotFound
from spotifagent.infrastructure.entrypoints.cli.dependencies import get_artist_repository
from spotifagent.infrastructure.entrypoints.cli.dependencies import get_db
from spotifagent.infrastructure.entrypoints.cli.dependencies import get_spotify_client
from spotifagent.infrastructure.entrypoints.cli.dependencies import get_spotify_user_session_factory
from spotifagent.infrastructure.entrypoints.cli.dependencies import get_track_repository
from spotifagent.infrastructure.entrypoints.cli.dependencies import get_user_repository


async def sync_logic(email: EmailStr, config: SyncConfig) -> SyncReport:
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
            raise UserNotFound()

        return await spotify_sync(
            user=user,
            spotify_session_factory=spotify_session_factory,
            artist_repository=artist_repository,
            track_repository=track_repository,
            config=config,
        )

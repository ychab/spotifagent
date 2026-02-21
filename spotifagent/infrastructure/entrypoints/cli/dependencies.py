from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from spotifagent.application.services.spotify import SpotifySessionFactory
from spotifagent.domain.ports.clients.lastfm import LastFmClientPort
from spotifagent.domain.ports.clients.spotify import SpotifyClientPort
from spotifagent.domain.ports.repositories.music import ArtistRepositoryPort
from spotifagent.domain.ports.repositories.music import TrackRepositoryPort
from spotifagent.domain.ports.repositories.spotify import SpotifyAccountRepositoryPort
from spotifagent.domain.ports.repositories.users import UserRepositoryPort
from spotifagent.domain.ports.security import PasswordHasherPort
from spotifagent.domain.ports.security import StateTokenGeneratorPort
from spotifagent.infrastructure.adapters.clients.lastfm import LastFmClientAdapter
from spotifagent.infrastructure.adapters.clients.spotify import SpotifyClientAdapter
from spotifagent.infrastructure.adapters.database.repositories.music import ArtistRepository
from spotifagent.infrastructure.adapters.database.repositories.music import TrackRepository
from spotifagent.infrastructure.adapters.database.repositories.spotify import SpotifyAccountRepository
from spotifagent.infrastructure.adapters.database.repositories.users import UserRepository
from spotifagent.infrastructure.adapters.database.session import session_scope
from spotifagent.infrastructure.adapters.security import Argon2PasswordHasher
from spotifagent.infrastructure.adapters.security import SystemStateTokenGenerator
from spotifagent.infrastructure.config.settings.lastfm import lastfm_settings
from spotifagent.infrastructure.config.settings.spotify import spotify_settings


def get_password_hasher() -> PasswordHasherPort:
    return Argon2PasswordHasher()


def get_state_token_generator() -> StateTokenGeneratorPort:
    return SystemStateTokenGenerator()


@asynccontextmanager
async def get_db() -> AsyncGenerator[AsyncSession]:
    async with session_scope() as session:
        yield session


@asynccontextmanager
async def get_spotify_client() -> AsyncGenerator[SpotifyClientPort]:
    async with SpotifyClientAdapter(
        client_id=spotify_settings.CLIENT_ID,
        client_secret=spotify_settings.CLIENT_SECRET,
        redirect_uri=spotify_settings.REDIRECT_URI,
        timeout=spotify_settings.HTTP_TIMEOUT,
        token_buffer_seconds=spotify_settings.TOKEN_BUFFER_SECONDS,
    ) as client:
        yield client


@asynccontextmanager
async def get_lastfm_client() -> AsyncGenerator[LastFmClientPort]:
    async with LastFmClientAdapter(
        client_api_key=lastfm_settings.CLIENT_API_KEY,
        client_secret=lastfm_settings.CLIENT_SECRET,
        timeout=lastfm_settings.HTTP_TIMEOUT,
    ) as client:
        yield client


def get_user_repository(session: AsyncSession) -> UserRepositoryPort:
    return UserRepository(session)


def get_spotify_account_repository(session: AsyncSession) -> SpotifyAccountRepositoryPort:
    return SpotifyAccountRepository(session)


def get_artist_repository(session: AsyncSession) -> ArtistRepositoryPort:
    return ArtistRepository(session)


def get_track_repository(session: AsyncSession) -> TrackRepositoryPort:
    return TrackRepository(session)


def get_spotify_user_session_factory(
    session: AsyncSession,
    spotify_client: SpotifyClientPort,
) -> SpotifySessionFactory:
    return SpotifySessionFactory(
        spotify_account_repository=get_spotify_account_repository(session),
        spotify_client=spotify_client,
    )

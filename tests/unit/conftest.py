from unittest import mock

import pytest

from spotifagent.domain.entities.spotify import SpotifyTokenState
from spotifagent.domain.entities.users import User
from spotifagent.domain.ports.clients.spotify import SpotifyClientPort
from spotifagent.domain.ports.repositories.music import ArtistRepositoryPort
from spotifagent.domain.ports.repositories.music import TrackRepositoryPort
from spotifagent.domain.ports.repositories.spotify import SpotifyAccountRepositoryPort
from spotifagent.domain.ports.repositories.users import UserRepositoryPort
from spotifagent.domain.ports.security import AccessTokenManagerPort
from spotifagent.domain.ports.security import PasswordHasherPort
from spotifagent.domain.ports.security import StateTokenGeneratorPort

from tests.unit.factories.spotify import SpotifyTokenStateFactory
from tests.unit.factories.users import UserFactory

# --- Security Mocks ---


@pytest.fixture
def mock_password_hasher() -> mock.Mock:
    return mock.Mock(spec=PasswordHasherPort)


@pytest.fixture
def mock_access_token_manager() -> mock.Mock:
    return mock.Mock(spec=AccessTokenManagerPort)


@pytest.fixture
def mock_state_token_generator() -> mock.Mock:
    return mock.Mock(spec=StateTokenGeneratorPort)


# --- Repository Mocks ---


@pytest.fixture
def mock_user_repository() -> mock.AsyncMock:
    return mock.AsyncMock(spec=UserRepositoryPort)


@pytest.fixture
def mock_spotify_account_repository() -> mock.AsyncMock:
    return mock.AsyncMock(spec=SpotifyAccountRepositoryPort)


@pytest.fixture
def mock_artist_repository() -> mock.AsyncMock:
    return mock.AsyncMock(spec=ArtistRepositoryPort)


@pytest.fixture
def mock_track_repository() -> mock.AsyncMock:
    return mock.AsyncMock(spec=TrackRepositoryPort)


# --- Entity Mocks ---


@pytest.fixture
def user(request: pytest.FixtureRequest) -> User:
    return UserFactory.build(**getattr(request, "param", {}))


@pytest.fixture
def token_state(request: pytest.FixtureRequest) -> SpotifyTokenState:
    return SpotifyTokenStateFactory.build(**getattr(request, "param", {}))


# --- Client Mocks ---


@pytest.fixture
def mock_spotify_client(token_state: SpotifyTokenState) -> mock.AsyncMock:
    return mock.AsyncMock(
        spec=SpotifyClientPort,
        refresh_access_token=mock.AsyncMock(return_value=token_state),
    )

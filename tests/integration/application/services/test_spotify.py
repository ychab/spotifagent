from unittest import mock

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import pytest

from spotifagent.application.services.spotify import SpotifyUserSession
from spotifagent.domain.entities.spotify import SpotifyTokenState
from spotifagent.domain.entities.users import User
from spotifagent.domain.ports.clients.spotify import SpotifyClientPort
from spotifagent.domain.ports.repositories.spotify import SpotifyAccountRepositoryPort
from spotifagent.infrastructure.adapters.database.models import User as UserModel


class TestSpotifyUserSession:
    @pytest.fixture
    def mock_spotify_client(self) -> mock.AsyncMock:
        return mock.AsyncMock(spec=SpotifyClientPort)

    @pytest.fixture
    def spotify_session(
        self,
        user: User,
        spotify_account_repository: SpotifyAccountRepositoryPort,
        mock_spotify_client: mock.AsyncMock,
    ) -> SpotifyUserSession:
        return SpotifyUserSession(
            user=user,
            spotify_account_repository=spotify_account_repository,
            spotify_client=mock_spotify_client,
        )

    @pytest.mark.parametrize("user", [{"with_spotify_account": True}], indirect=True)
    async def test__execute_request__persists_new_token(
        self,
        spotify_session: SpotifyUserSession,
        user: User,
        token_state: SpotifyTokenState,
        mock_spotify_client: mock.AsyncMock,
        async_session_db: AsyncSession,
    ) -> None:
        mock_spotify_client.refresh_access_token.return_value = token_state
        mock_spotify_client.make_user_api_call.return_value = ({"data": "ok"}, token_state)

        await spotify_session._execute_request("GET", "/test")

        # Check that token state is refresh in memory.
        assert spotify_session.user.spotify_account is not None
        assert spotify_session.user.spotify_account.token_type == token_state.token_type
        assert spotify_session.user.spotify_account.token_access == token_state.access_token
        assert spotify_session.user.spotify_account.token_refresh == token_state.refresh_token
        assert spotify_session.user.spotify_account.token_expires_at == token_state.expires_at

        # Check that token state is refresh in DB.
        stmt = select(UserModel).where(UserModel.email == user.email).options(selectinload(UserModel.spotify_account))
        result = await async_session_db.execute(stmt)
        user_db = result.scalar_one()

        assert user_db is not None
        assert user_db.spotify_account is not None
        assert user_db.spotify_account.token_type == token_state.token_type
        assert user_db.spotify_account.token_access == token_state.access_token
        assert user_db.spotify_account.token_refresh == token_state.refresh_token
        assert user_db.spotify_account.token_expires_at == token_state.expires_at

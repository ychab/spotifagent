from datetime import datetime
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import pytest
from pytest_httpx import HTTPXMock

from spotifagent.application.use_cases.spotify_oauth_callback import spotify_oauth_callback
from spotifagent.domain.entities.spotify import SpotifyTokenState
from spotifagent.domain.entities.users import User
from spotifagent.domain.ports.repositories.spotify import SpotifyAccountRepositoryPort
from spotifagent.domain.ports.repositories.users import UserRepositoryPort
from spotifagent.infrastructure.adapters.clients.spotify import SpotifyClientAdapter
from spotifagent.infrastructure.adapters.database.models import User as UserModel


class TestSpotifyOauthCallbackUseCase:
    @pytest.mark.parametrize("user", [{"spotify_state": None}], indirect=["user"])
    async def test__token_state__create(
        self,
        async_session_db: AsyncSession,
        frozen_time: datetime,
        user: User,
        token_state: SpotifyTokenState,
        user_repository: UserRepositoryPort,
        spotify_account_repository: SpotifyAccountRepositoryPort,
        spotify_client: SpotifyClientAdapter,
        httpx_mock: HTTPXMock,
    ) -> None:
        httpx_mock.add_response(
            url=str(spotify_client.token_endpoint),
            method="POST",
            json={
                "token_type": token_state.token_type,
                "access_token": token_state.access_token,
                "refresh_token": token_state.refresh_token,
                "expires_in": 3600,
            },
        )

        await spotify_oauth_callback(
            code="foo",
            user=user,
            user_repository=user_repository,
            spotify_account_repository=spotify_account_repository,
            spotify_client=spotify_client,
        )

        stmt = select(UserModel).where(UserModel.id == user.id).options(selectinload(UserModel.spotify_account))
        result = await async_session_db.execute(stmt)
        user_db = result.scalar_one()

        assert user_db.spotify_state is None
        assert user_db.spotify_account is not None
        assert user_db.spotify_account.token_type == token_state.token_type
        assert user_db.spotify_account.token_access == token_state.access_token
        assert user_db.spotify_account.token_refresh == token_state.refresh_token
        assert user_db.spotify_account.token_expires_at == frozen_time + timedelta(seconds=3600)

    @pytest.mark.parametrize("user", [{"spotify_state": None, "with_spotify_account": True}], indirect=["user"])
    async def test__token_state__update(
        self,
        async_session_db: AsyncSession,
        frozen_time: datetime,
        user: User,
        token_state: SpotifyTokenState,
        user_repository: UserRepositoryPort,
        spotify_account_repository: SpotifyAccountRepositoryPort,
        spotify_client: SpotifyClientAdapter,
        httpx_mock: HTTPXMock,
    ) -> None:
        httpx_mock.add_response(
            url=str(spotify_client.token_endpoint),
            method="POST",
            json={
                "token_type": token_state.token_type,
                "access_token": token_state.access_token,
                "refresh_token": token_state.refresh_token,
                "expires_in": 3600,
            },
        )

        await spotify_oauth_callback(
            code="foo",
            user=user,
            user_repository=user_repository,
            spotify_account_repository=spotify_account_repository,
            spotify_client=spotify_client,
        )

        stmt = select(UserModel).where(UserModel.id == user.id).options(selectinload(UserModel.spotify_account))
        result = await async_session_db.execute(stmt)
        user_db = result.scalar_one()

        assert user_db.spotify_state is None
        assert user_db.spotify_account is not None
        assert user_db.spotify_account.token_type == token_state.token_type
        assert user_db.spotify_account.token_access == token_state.access_token
        assert user_db.spotify_account.token_refresh == token_state.refresh_token
        assert user_db.spotify_account.token_expires_at == frozen_time + timedelta(seconds=3600)

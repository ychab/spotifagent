import asyncio
from collections.abc import AsyncGenerator
from collections.abc import Callable
from collections.abc import Iterable
from contextlib import asynccontextmanager
from unittest import mock

from sqlalchemy import insert
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import pytest

from spotifagent.domain.entities.spotify import SpotifyAccountCreate
from spotifagent.domain.entities.users import User
from spotifagent.domain.ports.clients.spotify import SpotifyClientPort
from spotifagent.infrastructure.adapters.database.models import SpotifyAccount as SpotifyAccountModel
from spotifagent.infrastructure.adapters.database.models import User as UserModel
from spotifagent.infrastructure.entrypoints.cli.commands.spotify import connect_logic

from tests.unit.factories.spotify import SpotifyAccountCreateFactory


class TestSpotifyConnectLogic:
    @pytest.fixture(autouse=True)
    def mock_typer_launch(self) -> Iterable[mock.Mock]:
        target_path = "spotifagent.infrastructure.entrypoints.cli.commands.spotify.connect.typer.launch"
        with mock.patch(target_path) as patched:
            yield patched

    @pytest.fixture
    def mock_spotify_client(self) -> Iterable[mock.Mock]:
        spotify_client = mock.Mock(spec=SpotifyClientPort)

        @asynccontextmanager
        async def mock_dependency() -> AsyncGenerator[SpotifyClientPort]:
            yield spotify_client

        target_path = "spotifagent.infrastructure.entrypoints.cli.commands.spotify.connect.get_spotify_client"
        with mock.patch(target_path, side_effect=mock_dependency):
            yield spotify_client

    @pytest.fixture
    async def spotify_account(self) -> SpotifyAccountCreate:
        return SpotifyAccountCreateFactory.build()

    @pytest.fixture
    def simulate_oauth_callback(
        self,
        user: User,
        spotify_account: SpotifyAccountCreate,
        async_session_db: AsyncSession,
    ) -> Callable[[float], asyncio.Task]:
        """
        Helper to simulate the external OAuth callback in the background.
        Yeah, I had to confess for this one: thank Gemini pro!
        """

        def _trigger(delay: float = 0.2) -> asyncio.Task:
            async def _background_update():
                # Wait for the CLI to start polling
                await asyncio.sleep(delay)

                # Unset user spotify state.
                stmt = update(UserModel).where(UserModel.email == str(user.email)).values(spotify_state=None)
                await async_session_db.execute(stmt)

                # Then create a new account.
                stmt = insert(SpotifyAccountModel).values(
                    user_id=user.id,
                    token_type=spotify_account.token_type,
                    token_access=spotify_account.token_access,
                    token_refresh=spotify_account.token_refresh,
                    token_expires_at=spotify_account.token_expires_at,
                )
                await async_session_db.execute(stmt)

                # Flush to make this change visible to the CLI's query
                await async_session_db.flush()

            return asyncio.create_task(_background_update())

        return _trigger

    async def test__nominal(
        self,
        user: User,
        spotify_account: SpotifyAccountCreate,
        mock_spotify_client: mock.Mock,
        simulate_oauth_callback: Callable[[float], asyncio.Task],
        async_session_db: AsyncSession,
        capsys: pytest.CaptureFixture,
    ) -> None:
        mock_spotify_client.get_authorization_url.return_value = "http://example.com", "dummy-token-state"

        # Start the "callback" simulator in the background
        task = simulate_oauth_callback(0.2)

        await connect_logic(user.email, timeout=2.0, poll_interval=0.1)
        # Ensure the background task completed without error
        await task

        stmt = select(UserModel).where(UserModel.email == user.email).options(selectinload(UserModel.spotify_account))
        result = await async_session_db.execute(stmt)
        user_db = result.scalar_one()

        assert user_db is not None
        assert user_db.spotify_state is None
        assert user_db.spotify_account is not None
        assert user_db.spotify_account.token_type == spotify_account.token_type
        assert user_db.spotify_account.token_access == spotify_account.token_access
        assert user_db.spotify_account.token_refresh == spotify_account.token_refresh
        assert user_db.spotify_account.token_expires_at == spotify_account.token_expires_at

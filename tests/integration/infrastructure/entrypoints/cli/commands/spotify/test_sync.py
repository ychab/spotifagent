from collections.abc import Iterable
from unittest import mock

import pytest

from spotifagent.application.use_cases.spotify_sync import SyncReport
from spotifagent.domain.entities.users import User
from spotifagent.infrastructure.entrypoints.cli.commands.spotify import sync_logic


class TestSpotifySyncLogic:
    """
    The purpose of this test is to check that the user repository is loading
    as expected. Otherwise, we trust use case integration tests and prevent duplicate.
    """

    @pytest.fixture
    def mock_spotify_sync(self) -> Iterable[mock.AsyncMock]:
        target_path = "spotifagent.infrastructure.entrypoints.cli.commands.spotify.sync.spotify_sync"
        with mock.patch(target_path, new_callable=mock.AsyncMock) as patched:
            yield patched

    async def test__artist_top__nominal(
        self,
        user: User,
        mock_spotify_sync: mock.AsyncMock,
        capsys: pytest.CaptureFixture,
    ) -> None:
        mock_spotify_sync.return_value = SyncReport(
            artist_created=100,
            artist_updated=250,
            track_created=100,
            track_updated=250,
        )

        await sync_logic(user.email, sync_artist_top=True, sync_track_top=True, sync_track_saved=True)

        captured = capsys.readouterr()
        assert "Synchronization successful!" in captured.out
        assert "- 100 artists created" in captured.out
        assert "- 250 artists updated" in captured.out
        assert "- 100 tracks created" in captured.out
        assert "- 250 tracks updated" in captured.out

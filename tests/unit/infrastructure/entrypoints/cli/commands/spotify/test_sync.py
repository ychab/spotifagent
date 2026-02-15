from collections.abc import Iterable
from typing import Any
from typing import Final
from typing import get_args
from unittest import mock

import pytest
import typer
from typer.testing import CliRunner

from spotifagent.application.services.spotify import TimeRange
from spotifagent.application.use_cases.spotify_sync import SyncReport
from spotifagent.domain.entities.users import User
from spotifagent.infrastructure.entrypoints.cli.commands.spotify import sync_logic
from spotifagent.infrastructure.entrypoints.cli.main import app

from tests.unit.factories.users import UserFactory
from tests.unit.infrastructure.entrypoints.cli.conftest import TextCleaner

TIME_RANGE_OPTIONS_OUTPUT: Final[str] = ", ".join([f"'{tr}'" for tr in get_args(TimeRange)])


class TestSpotifySyncCommand:
    @pytest.fixture(autouse=True)
    def mock_sync_logic(self) -> Iterable[mock.AsyncMock]:
        target_path = "spotifagent.infrastructure.entrypoints.cli.commands.spotify.sync_logic"
        with mock.patch(target_path, new_callable=mock.AsyncMock) as patched:
            yield patched

    def test__nominal(self, runner: CliRunner) -> None:
        # fmt: off
        result = runner.invoke(
            app,
            [
                "spotify",
                "sync",
                "--email", "test@example.com",
                "--purge-artist-top",
                "--purge-track-top",
                "--purge-track-saved",
                "--no-sync-artist-top",
                "--no-sync-track-top",
                "--no-sync-track-saved",
                "--page-limit", "20",
                "--time-range", "medium_term",
                "--batch-size", "100",
            ],
        )
        # fmt: on
        assert result.exit_code == 0

    @pytest.mark.parametrize(
        ("email", "expected_msg"),
        [
            pytest.param(
                "testtest.com",
                "An email address must have an @-sign",
                id="missing_@",
            ),
            pytest.param(
                "test@test",
                "The part after the @-sign is not valid. It should have a period",
                id="missing_dot",
            ),
        ],
    )
    def test__email__invalid(
        self,
        runner: CliRunner,
        email: str,
        expected_msg: str,
        clean_typer_text: TextCleaner,
    ) -> None:
        result = runner.invoke(app, ["spotify", "sync", "--email", email])
        assert result.exit_code != 0

        output = clean_typer_text(result.output)
        assert f"Invalid value for '--email': value is not a valid email address: {expected_msg}" in output

    @pytest.mark.parametrize(
        ("page_limit", "expected_msg"),
        [
            pytest.param(0, "Invalid value for '--page-limit': 0 is not in the range", id="zero"),
            pytest.param(-15, "Invalid value for '--page-limit': -15 is not in the range", id="min_exceed"),
            pytest.param(55, "Invalid value for '--page-limit': 55 is not in the range", id="max_exceed"),
            pytest.param("foo", "Invalid value for '--page-limit': 'foo' is not a valid integer", id="string"),
        ],
    )
    def test__page_limit__invalid(
        self,
        runner: CliRunner,
        page_limit: Any,
        expected_msg: str,
        clean_typer_text: TextCleaner,
    ) -> None:
        result = runner.invoke(
            app,
            ["spotify", "sync", "--email", "test@example.com", "--page-limit", page_limit],
        )
        assert result.exit_code != 0

        output = clean_typer_text(result.output)
        assert expected_msg in output

    @pytest.mark.parametrize(
        ("time_range", "expected_msg"),
        [
            pytest.param(
                "foo",
                f"Invalid value for '--time-range': 'foo' is not one of {TIME_RANGE_OPTIONS_OUTPUT}",
                id="invalid-choice",
            ),
        ],
    )
    def test__time_range__invalid(
        self,
        runner: CliRunner,
        time_range: Any,
        expected_msg: str,
        clean_typer_text: TextCleaner,
    ) -> None:
        result = runner.invoke(
            app,
            ["spotify", "sync", "--email", "test@example.com", "--time-range", time_range],
        )
        assert result.exit_code != 0

        output = clean_typer_text(result.output)
        assert expected_msg in output

    @pytest.mark.parametrize(
        ("batch_size", "expected_msg"),
        [
            pytest.param(0, "Invalid value for '--batch-size': 0 is not in the range", id="zero"),
            pytest.param(-15, "Invalid value for '--batch-size': -15 is not in the range", id="min_exceed"),
            pytest.param(1000, "Invalid value for '--batch-size': 1000 is not in the range", id="max_exceed"),
            pytest.param("foo", "Invalid value for '--batch-size': 'foo' is not a valid integer", id="string"),
        ],
    )
    def test__batch_size__invalid(
        self,
        runner: CliRunner,
        batch_size: Any,
        expected_msg: str,
        clean_typer_text: TextCleaner,
    ) -> None:
        result = runner.invoke(
            app,
            ["spotify", "sync", "--email", "test@example.com", "--batch-size", batch_size],
        )
        assert result.exit_code != 0

        output = clean_typer_text(result.output)
        assert expected_msg in output


@pytest.mark.usefixtures(
    "mock_get_db",
    "mock_user_repository",
    "mock_artist_repository",
    "mock_track_repository",
    "mock_spotify_client",
)
class TestSpotifySyncLogic:
    TARGET_PATH: Final[str] = "spotifagent.infrastructure.entrypoints.cli.commands.spotify.sync"

    @pytest.fixture(autouse=True)
    def mock_spotify_sync(self) -> Iterable[mock.AsyncMock]:
        with mock.patch(f"{self.TARGET_PATH}.spotify_sync", new_callable=mock.AsyncMock) as patched:
            yield patched

    @pytest.fixture(autouse=True)
    def mock_typer_launch(self) -> Iterable[mock.Mock]:
        with mock.patch(f"{self.TARGET_PATH}.typer.launch") as patched:
            yield patched

    @pytest.fixture
    def user(self) -> User:
        return UserFactory.build(with_spotify_account=True)

    async def test__do_nothing(
        self,
        user: User,
        mock_user_repository: mock.AsyncMock,
        mock_spotify_sync: mock.AsyncMock,
        capsys: pytest.CaptureFixture,
    ) -> None:
        mock_user_repository.get_by_email.return_value = user
        mock_spotify_sync.return_value = SyncReport()

        with pytest.raises(typer.Abort):
            await sync_logic(
                user.email,
                purge_artist_top=False,
                purge_track_top=False,
                purge_track_saved=False,
                sync_artist_top=False,
                sync_track_top=False,
                sync_track_saved=False,
            )

        captured = capsys.readouterr()
        assert "At least one flag must be provided." in captured.err

    async def test__user__not_found(
        self,
        mock_user_repository: mock.AsyncMock,
        mock_spotify_sync: mock.AsyncMock,
    ) -> None:
        mock_user_repository.get_by_email.return_value = None

        email = "test@example.com"
        with pytest.raises(typer.BadParameter, match=f"User not found with email: {email}"):
            await sync_logic(email, sync_artist_top=True)

    async def test__output__errors(
        self,
        user: User,
        mock_user_repository: mock.AsyncMock,
        mock_spotify_sync: mock.AsyncMock,
        capsys: pytest.CaptureFixture,
    ) -> None:
        mock_user_repository.get_by_email.return_value = user
        mock_spotify_sync.return_value = SyncReport(errors=["An error occurred: Boom"])

        with pytest.raises(typer.Abort):
            await sync_logic(user.email, sync_artist_top=True)

        captured = capsys.readouterr()
        assert "An error occurred: Boom" in captured.err

    async def test__output__purge_artists(
        self,
        user: User,
        mock_user_repository: mock.AsyncMock,
        mock_spotify_sync: mock.AsyncMock,
        capsys: pytest.CaptureFixture,
    ) -> None:
        mock_user_repository.get_by_email.return_value = user
        mock_spotify_sync.return_value = SyncReport(purge_artist=330)

        await sync_logic(
            user.email,
            purge_artist_top=True,
            purge_track_top=False,
            purge_track_saved=False,
            sync_artist_top=False,
            sync_track_top=False,
            sync_track_saved=False,
        )

        captured = capsys.readouterr()
        assert "Synchronization successful!" in captured.out
        assert "- 330 artists purged" in captured.out

    @pytest.mark.parametrize(("purge_track_top", "purge_track_saved"), [(True, False), (False, True), (True, True)])
    async def test__output__purge_tracks(
        self,
        user: User,
        purge_track_top: bool,
        purge_track_saved: bool,
        mock_user_repository: mock.AsyncMock,
        mock_spotify_sync: mock.AsyncMock,
        capsys: pytest.CaptureFixture,
    ) -> None:
        mock_user_repository.get_by_email.return_value = user
        mock_spotify_sync.return_value = SyncReport(purge_track=550)

        await sync_logic(
            user.email,
            purge_artist_top=False,
            purge_track_top=purge_track_top,
            purge_track_saved=purge_track_saved,
            sync_artist_top=False,
            sync_track_top=False,
        )

        captured = capsys.readouterr()
        assert "Synchronization successful!" in captured.out
        assert "- 550 tracks purged" in captured.out

    async def test__output__sync_artists_top(
        self,
        user: User,
        mock_user_repository: mock.AsyncMock,
        mock_spotify_sync: mock.AsyncMock,
        capsys: pytest.CaptureFixture,
    ) -> None:
        mock_user_repository.get_by_email.return_value = user
        mock_spotify_sync.return_value = SyncReport(
            artist_created=100,
            artist_updated=250,
        )

        await sync_logic(
            user.email,
            purge_artist_top=False,
            purge_track_top=False,
            purge_track_saved=False,
            sync_artist_top=True,
            sync_track_top=False,
            sync_track_saved=False,
        )

        captured = capsys.readouterr()
        assert "Synchronization successful!" in captured.out
        assert "- 100 artists created" in captured.out
        assert "- 250 artists updated" in captured.out

    @pytest.mark.parametrize(("sync_track_top", "sync_track_saved"), [(True, False), (False, True), (True, True)])
    async def test__output__sync_tracks(
        self,
        user: User,
        sync_track_top: bool,
        sync_track_saved: bool,
        mock_user_repository: mock.AsyncMock,
        mock_spotify_sync: mock.AsyncMock,
        capsys: pytest.CaptureFixture,
    ) -> None:
        mock_user_repository.get_by_email.return_value = user
        mock_spotify_sync.return_value = SyncReport(
            track_created=50,
            track_updated=150,
        )

        await sync_logic(
            user.email,
            purge_artist_top=False,
            purge_track_top=False,
            purge_track_saved=False,
            sync_artist_top=False,
            sync_track_top=sync_track_top,
            sync_track_saved=sync_track_saved,
        )

        captured = capsys.readouterr()
        assert "Synchronization successful!" in captured.out
        assert "- 50 tracks created" in captured.out
        assert "- 150 tracks updated" in captured.out

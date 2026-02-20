from collections.abc import Iterable
from typing import Any
from typing import Final
from typing import get_args
from unittest import mock

import pytest
from typer.testing import CliRunner

from spotifagent.application.services.spotify import TimeRange
from spotifagent.application.use_cases.spotify_sync import SyncConfig
from spotifagent.application.use_cases.spotify_sync import SyncReport
from spotifagent.domain.exceptions import UserNotFound
from spotifagent.infrastructure.entrypoints.cli.commands.spotify import sync_logic
from spotifagent.infrastructure.entrypoints.cli.main import app

from tests.unit.infrastructure.entrypoints.cli.conftest import TextCleaner

TIME_RANGE_OPTIONS_OUTPUT: Final[str] = ", ".join([f"'{tr}'" for tr in get_args(TimeRange)])


class TestSpotifySyncParserCommand:
    @pytest.fixture(autouse=True)
    def mock_sync_logic(self) -> Iterable[mock.AsyncMock]:
        target_path = "spotifagent.infrastructure.entrypoints.cli.commands.spotify.sync_logic"
        with mock.patch(target_path, new_callable=mock.AsyncMock) as patched:
            patched.return_value = SyncReport()
            yield patched

    def test__nominal(self, runner: CliRunner) -> None:
        # fmt: off
        result = runner.invoke(
            app,
            [
                "spotify",
                "sync",
                "--email", "test@example.com",
                "--purge",
                "--purge-artist-top",
                "--purge-track-top",
                "--purge-track-saved",
                "--purge-track-playlist",
                "--no-sync",
                "--no-sync-artist-top",
                "--no-sync-track-top",
                "--no-sync-track-saved",
                "--no-sync-track-playlist",
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


class TestSpotifySyncCommand:
    @pytest.fixture(autouse=True)
    def mock_sync_logic(self) -> Iterable[mock.AsyncMock]:
        target_path = "spotifagent.infrastructure.entrypoints.cli.commands.spotify.sync_logic"
        with mock.patch(target_path, new_callable=mock.AsyncMock) as patched:
            yield patched

    def test__do_nothing(
        self,
        runner: CliRunner,
        clean_typer_text: TextCleaner,
    ) -> None:
        result = runner.invoke(app, ["spotify", "sync", "--email", "test@example.com"])
        assert result.exit_code != 0

        output = clean_typer_text(result.stderr)
        assert "At least one flag must be provided" in output

    def test__user_not_found(
        self,
        mock_sync_logic: mock.AsyncMock,
        runner: CliRunner,
        clean_typer_text: TextCleaner,
    ) -> None:
        mock_sync_logic.side_effect = UserNotFound()

        result = runner.invoke(app, ["spotify", "sync", "--email", "test@example.com", "--sync"])
        assert result.exit_code != 0

        output = clean_typer_text(result.stderr)
        assert "User not found with email: test@example.com" in output

    def test__output__exceptions(
        self,
        mock_sync_logic: mock.AsyncMock,
        runner: CliRunner,
        clean_typer_text: TextCleaner,
    ) -> None:
        mock_sync_logic.side_effect = Exception("Boom")

        result = runner.invoke(app, ["spotify", "sync", "--email", "test@example.com", "--sync"])
        assert result.exit_code != 0

        output = clean_typer_text(result.stderr)
        assert "Error: Boom" in output

    def test__output__report_errors(
        self,
        mock_sync_logic: mock.AsyncMock,
        runner: CliRunner,
        clean_typer_text: TextCleaner,
    ) -> None:
        mock_sync_logic.return_value = SyncReport(errors=["An error occurred: Boom"])

        result = runner.invoke(app, ["spotify", "sync", "--email", "test@example.com", "--sync"])
        assert result.exit_code != 0

        output = clean_typer_text(result.stderr)
        assert "An error occurred: Boom" in output

    @pytest.mark.parametrize("cmd_args", [["--purge"], ["--purge-artist-top"], ["--purge", "--purge-artist-top"]])
    def test__output__purge_artists(
        self,
        cmd_args: list[str],
        mock_sync_logic: mock.AsyncMock,
        runner: CliRunner,
        clean_typer_text: TextCleaner,
    ) -> None:
        mock_sync_logic.return_value = SyncReport(purge_artist=330)

        result = runner.invoke(app, ["spotify", "sync", "--email", "test@example.com", *cmd_args])
        assert result.exit_code == 0

        output = clean_typer_text(result.stdout)
        assert "Synchronization successful in " in output
        assert "Artists purged 330" in output

    @pytest.mark.parametrize(
        "cmd_args",
        [
            ["--purge"],
            ["--purge-track-top"],
            ["--purge-track-saved"],
            ["--purge-track-playlist"],
            ["--purge", "--purge-track-top"],
            ["--purge", "--purge-track-saved"],
            ["--purge", "--purge-track-playlist"],
            ["--purge-track-top", "--purge-track-saved"],
            ["--purge-track-top", "--purge-track-playlist"],
            ["--purge-track-saved", "--purge-track-playlist"],
            ["--purge", "--purge-track-top", "--purge-track-saved"],
            ["--purge", "--purge-track-top", "--purge-track-playlist"],
            ["--purge", "--purge-track-saved", "--purge-track-playlist"],
            ["--purge-track-top", "--purge-track-saved", "--purge-track-playlist"],
            ["--purge", "--purge-track-top", "--purge-track-saved", "--purge-track-playlist"],
        ],
    )
    def test__output__purge_tracks(
        self,
        cmd_args: list[str],
        mock_sync_logic: mock.AsyncMock,
        runner: CliRunner,
        clean_typer_text: TextCleaner,
    ) -> None:
        mock_sync_logic.return_value = SyncReport(purge_track=550)

        result = runner.invoke(app, ["spotify", "sync", "--email", "test@example.com", *cmd_args])
        assert result.exit_code == 0

        output = clean_typer_text(result.stdout)
        assert "Synchronization successful in " in output
        assert "Tracks purged 550" in output

    @pytest.mark.parametrize("cmd_args", [["--sync"], ["--sync-artist-top"], ["--sync", "--sync-artist-top"]])
    def test__output__sync_artists_top(
        self,
        cmd_args: list[str],
        mock_sync_logic: mock.AsyncMock,
        runner: CliRunner,
        clean_typer_text: TextCleaner,
    ) -> None:
        mock_sync_logic.return_value = SyncReport(
            artist_created=100,
            artist_updated=250,
        )

        result = runner.invoke(app, ["spotify", "sync", "--email", "test@example.com", *cmd_args])
        assert result.exit_code == 0

        output = clean_typer_text(result.stdout)
        assert "Synchronization successful in " in output
        assert "Artists created 100" in output
        assert "Artists updated 250" in output

    @pytest.mark.parametrize(
        "cmd_args",
        [
            ["--sync"],
            ["--sync-track-top"],
            ["--sync-track-saved"],
            ["--sync-track-playlist"],
            ["--sync", "--sync-track-top"],
            ["--sync", "--sync-track-saved"],
            ["--sync", "--sync-track-playlist"],
            ["--sync-track-top", "--sync-track-saved"],
            ["--sync-track-top", "--sync-track-playlist"],
            ["--sync-track-saved", "--sync-track-playlist"],
            ["--sync", "--sync-track-top", "--sync-track-saved"],
            ["--sync", "--sync-track-top", "--sync-track-playlist"],
            ["--sync", "--sync-track-saved", "--sync-track-playlist"],
            ["--sync-track-top", "--sync-track-saved", "--sync-track-playlist"],
            ["--sync", "--sync-track-top", "--sync-track-saved", "--sync-track-playlist"],
        ],
    )
    def test__output__sync_tracks(
        self,
        cmd_args: list[str],
        mock_sync_logic: mock.AsyncMock,
        runner: CliRunner,
        clean_typer_text: TextCleaner,
    ) -> None:
        mock_sync_logic.return_value = SyncReport(
            track_created=50,
            track_updated=150,
        )

        result = runner.invoke(app, ["spotify", "sync", "--email", "test@example.com", *cmd_args])
        assert result.exit_code == 0

        output = clean_typer_text(result.stdout)
        assert "Synchronization successful in " in output
        assert "Tracks created 50" in output
        assert "Tracks updated 150" in output


@pytest.mark.usefixtures(
    "mock_get_db",
    "mock_user_repository",
    "mock_artist_repository",
    "mock_track_repository",
    "mock_spotify_client",
)
class TestSpotifySyncLogic:
    TARGET_PATH: Final[str] = "spotifagent.infrastructure.entrypoints.cli.commands.spotify.sync"

    async def test__user__not_found(self, mock_user_repository: mock.AsyncMock) -> None:
        mock_user_repository.get_by_email.return_value = None

        email = "test@example.com"
        with pytest.raises(UserNotFound):
            await sync_logic(email, config=SyncConfig(sync=True))

from collections.abc import Iterable
from typing import Any
from typing import Final
from unittest import mock

import pytest
from typer.testing import CliRunner

from spotifagent.domain.entities.users import User
from spotifagent.domain.exceptions import UserNotFound
from spotifagent.infrastructure.entrypoints.cli.commands.spotify import connect_logic
from spotifagent.infrastructure.entrypoints.cli.main import app

from tests.unit.infrastructure.entrypoints.cli.conftest import TextCleaner


class TestSpotifyConnectParserCommand:
    @pytest.fixture(autouse=True)
    def mock_connect_logic(self) -> Iterable[mock.AsyncMock]:
        target_path = "spotifagent.infrastructure.entrypoints.cli.commands.spotify.connect_logic"
        with mock.patch(target_path, new_callable=mock.AsyncMock) as patched:
            yield patched

    def test__nominal(self, runner: CliRunner) -> None:
        result = runner.invoke(
            app,
            ["spotify", "connect", "--email", "test@example.com", "--timeout", "30.0", "--poll-interval", "0.5"],
        )
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
        result = runner.invoke(
            app,
            ["spotify", "connect", "--email", email],
        )
        assert result.exit_code != 0

        output = clean_typer_text(result.output)
        assert f"Invalid value for '--email': value is not a valid email address: {expected_msg}" in output

    @pytest.mark.parametrize(
        ("timeout", "expected_msg"),
        [
            pytest.param(0.0, "Invalid value for '--timeout': 0.0 is not in the range", id="zero"),
            pytest.param(-15.5, "Invalid value for '--timeout': -15.5 is not in the range", id="negative"),
            pytest.param("foo", "Invalid value for '--timeout': 'foo' is not a valid float", id="string"),
        ],
    )
    def test__timeout__invalid(
        self,
        runner: CliRunner,
        timeout: Any,
        expected_msg: str,
        clean_typer_text: TextCleaner,
    ) -> None:
        result = runner.invoke(
            app,
            ["spotify", "connect", "--email", "test@example.com", "--timeout", timeout],
        )
        assert result.exit_code != 0

        output = clean_typer_text(result.output)
        assert expected_msg in output

    @pytest.mark.parametrize(
        ("poll_interval", "expected_msg"),
        [
            pytest.param(0.0, "Invalid value for '--poll-interval': 0.0 is not in the range", id="zero"),
            pytest.param(-15.5, "Invalid value for '--poll-interval': -15.5 is not in the range", id="negative"),
            pytest.param("foo", "Invalid value for '--poll-interval': 'foo' is not a valid float", id="string"),
        ],
    )
    def test__poll_interval__invalid(
        self,
        runner: CliRunner,
        poll_interval: Any,
        expected_msg: str,
        clean_typer_text: TextCleaner,
    ) -> None:
        result = runner.invoke(
            app,
            ["spotify", "connect", "--email", "test@example.com", "--poll-interval", poll_interval],
        )
        assert result.exit_code != 0

        output = clean_typer_text(result.output)
        assert expected_msg in output


class TestSpotifyConnectCommand:
    @pytest.fixture(autouse=True)
    def mock_connect_logic(self) -> Iterable[mock.AsyncMock]:
        target_path = "spotifagent.infrastructure.entrypoints.cli.commands.spotify.connect_logic"
        with mock.patch(target_path, new_callable=mock.AsyncMock) as patched:
            yield patched

    def test__nominal(
        self,
        mock_connect_logic: mock.AsyncMock,
        runner: CliRunner,
        clean_typer_text: TextCleaner,
    ) -> None:
        result = runner.invoke(app, ["spotify", "connect", "--email", "test@example.com"])
        assert result.exit_code == 0

        output = clean_typer_text(result.stdout)
        assert "Authentication successful!" in output

    def test__user_not_found(
        self,
        mock_connect_logic: mock.AsyncMock,
        runner: CliRunner,
        clean_typer_text: TextCleaner,
    ) -> None:
        mock_connect_logic.side_effect = UserNotFound()

        result = runner.invoke(app, ["spotify", "connect", "--email", "test@example.com"])
        assert result.exit_code != 0

        output = clean_typer_text(result.stderr)
        assert "User not found with email: test@example.com" in output

    def test__timeout__exceed(
        self,
        mock_connect_logic: mock.AsyncMock,
        runner: CliRunner,
        clean_typer_text: TextCleaner,
    ) -> None:
        mock_connect_logic.side_effect = TimeoutError()

        result = runner.invoke(app, ["spotify", "connect", "--email", "test@example.com", "--timeout", "10"])
        assert result.exit_code != 0

        output = clean_typer_text(result.stderr)
        assert "Unable to connect after 10.0 seconds. Did you open your browser and accept?" in output

    def test__exception(
        self,
        mock_connect_logic: mock.AsyncMock,
        runner: CliRunner,
        clean_typer_text: TextCleaner,
    ) -> None:
        mock_connect_logic.side_effect = Exception("Boom")

        result = runner.invoke(app, ["spotify", "connect", "--email", "test@example.com"])
        assert result.exit_code != 0

        output = clean_typer_text(result.stderr)
        assert "Error: Boom" in output


@pytest.mark.usefixtures("mock_get_db", "mock_user_repository", "mock_spotify_client")
class TestSpotifyConnectLogic:
    TARGET_PATH: Final[str] = "spotifagent.infrastructure.entrypoints.cli.commands.spotify.connect"

    @pytest.fixture(autouse=True)
    def mock_typer_launch(self) -> Iterable[mock.Mock]:
        with mock.patch(f"{self.TARGET_PATH}.typer.launch") as patched:
            yield patched

    async def test__user_not_found(self, mock_user_repository: mock.AsyncMock) -> None:
        mock_user_repository.get_by_email.return_value = None

        email = "test@example.com"
        with pytest.raises(UserNotFound):
            await connect_logic(email, 10, 2)

    @pytest.mark.parametrize("user", [{"spotify_state": "dummy-token-state"}], indirect=True)
    async def test__timeout__exceed(
        self,
        mock_user_repository: mock.AsyncMock,
        mock_spotify_client: mock.Mock,
        user: User,
    ) -> None:
        mock_user_repository.get_by_email.return_value = user
        mock_spotify_client.get_authorization_url.return_value = "http://example.com", "dummy-token-state"

        timeout = 0.1
        with pytest.raises(TimeoutError):
            await connect_logic(user.email, timeout=timeout, poll_interval=0.05)

from collections.abc import Iterable
from unittest import mock

import pytest
from typer.testing import CliRunner

from spotifagent.domain.exceptions import UserAlreadyExistsException
from spotifagent.infrastructure.entrypoints.cli.main import app

from tests.unit.infrastructure.entrypoints.cli.conftest import TextCleaner


class TestUserCreateParserCommand:
    @pytest.fixture(autouse=True)
    def mock_create_user_logic(self) -> Iterable[mock.AsyncMock]:
        target_path = "spotifagent.infrastructure.entrypoints.cli.commands.users.user_create_logic"
        with mock.patch(target_path, new_callable=mock.AsyncMock) as patched:
            yield patched

    def test__nominal(self, runner: CliRunner) -> None:
        result = runner.invoke(
            app,
            ["users", "create", "--email", "test@example.com", "--password", "testtest"],
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
            ["users", "create", "--email", email, "--password", "testtest"],
        )
        assert result.exit_code != 0

        output = clean_typer_text(result.output)
        assert f"Invalid value for '--email': value is not a valid email address: {expected_msg}" in output

    @pytest.mark.parametrize("password", ["test", "".join("test" for _ in range(30))], ids=["too_short", "too_long"])
    def test__password__invalid__prompt(self, password: str, runner: CliRunner) -> None:
        result = runner.invoke(
            app,
            ["users", "create", "--email", "cli_test@example.com"],
            input=f"{password}\n{password}\n",
        )
        assert result.exit_code != 0
        assert "Password: \nError: The value you entered was invalid." in result.stdout

    @pytest.mark.parametrize(
        ("password", "expected_msg"),
        [
            pytest.param(
                "test",
                "String should have at least 8 characters",
                id="too_short",
            ),
            pytest.param(
                "".join("test" for _ in range(30)),
                "String should have at most 100 characters",
                id="too_long",
            ),
        ],
    )
    def test__password__invalid__flag(self, runner: CliRunner, password: str, expected_msg: str) -> None:
        result = runner.invoke(
            app,
            ["users", "create", "--email", "cli_test@example.com", "--password", password],
        )
        assert result.exit_code != 0
        assert f"Invalid value for '--password': {expected_msg}" in result.output


class TestUserCreateCommand:
    @pytest.fixture
    def mock_user_create_logic(self) -> Iterable[mock.AsyncMock]:
        target_path = "spotifagent.infrastructure.entrypoints.cli.commands.users.user_create_logic"
        with mock.patch(target_path, new_callable=mock.AsyncMock) as patched:
            yield patched

    def test__nominal(
        self,
        mock_user_create_logic: mock.AsyncMock,
        runner: CliRunner,
        clean_typer_text: TextCleaner,
    ) -> None:
        result = runner.invoke(app, ["users", "create", "--email", "test@example.com", "--password", "testtest"])
        assert result.exit_code == 0

        output = clean_typer_text(result.stdout)
        assert "User test@example.com created successfully!" in output

    def test__user_already_exists(
        self,
        mock_user_create_logic: mock.AsyncMock,
        runner: CliRunner,
        clean_typer_text: TextCleaner,
    ) -> None:
        mock_user_create_logic.side_effect = UserAlreadyExistsException()

        result = runner.invoke(app, ["users", "create", "--email", "test@example.com", "--password", "testtest"])
        assert result.exit_code != 0

        output = clean_typer_text(result.stderr)
        assert "User with email test@example.com already exists." in output

    def test__unexpected_exceptions(
        self,
        mock_user_create_logic: mock.AsyncMock,
        runner: CliRunner,
        clean_typer_text: TextCleaner,
    ) -> None:
        mock_user_create_logic.side_effect = Exception("Boom")

        result = runner.invoke(app, ["users", "create", "--email", "test@example.com", "--password", "testtest"])
        assert result.exit_code != 0

        output = clean_typer_text(result.stderr)
        assert "Error: Boom" in output

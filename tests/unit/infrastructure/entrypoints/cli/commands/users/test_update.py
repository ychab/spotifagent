import uuid
from collections.abc import Iterable
from typing import Final
from unittest import mock

import pytest
from typer.testing import CliRunner

from spotifagent.domain.entities.users import UserUpdate
from spotifagent.domain.exceptions import UserNotFound
from spotifagent.infrastructure.entrypoints.cli.commands.users import user_update_logic
from spotifagent.infrastructure.entrypoints.cli.main import app

from tests.unit.infrastructure.entrypoints.cli.conftest import TextCleaner


class TestUserUpdateParserCommand:
    @pytest.fixture(autouse=True)
    def mock_user_update_logic(self) -> Iterable[mock.AsyncMock]:
        target_path = "spotifagent.infrastructure.entrypoints.cli.commands.users.user_update_logic"
        with mock.patch(target_path, new_callable=mock.AsyncMock) as patched:
            yield patched

    def test__nominal(self, runner: CliRunner) -> None:
        # fmt: off
        cmd_args = [
            "users", "update", f"{uuid.uuid4()}",
            "--email", "test@example.com",
            "--password", "testtest",
        ]
        # fmt: on

        result = runner.invoke(app, cmd_args)
        assert result.exit_code == 0

    @pytest.mark.parametrize("user_id", ["123456", "foo-bar-baz"])
    def test__user_id__invalid(self, runner: CliRunner, user_id: str, clean_typer_text: TextCleaner) -> None:
        result = runner.invoke(
            app,
            ["users", "update", f"{user_id}", "--email", "test@example.com"],
        )
        assert result.exit_code != 0

        output = clean_typer_text(result.output)
        assert f"Invalid value for 'USER_ID': '{user_id}' is not a valid UUID." in output

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
            ["users", "update", f"{uuid.uuid4()}", "--email", email],
        )
        assert result.exit_code != 0

        output = clean_typer_text(result.output)
        assert f"Invalid value for '--email': value is not a valid email address: {expected_msg}" in output

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
            ["users", "update", f"{uuid.uuid4()}", "--password", password],
        )
        assert result.exit_code != 0
        assert f"Invalid value for '--password': {expected_msg}" in result.output


class TestUserUpdateCommand:
    @pytest.fixture(autouse=True)
    def mock_user_update_logic(self) -> Iterable[mock.AsyncMock]:
        target_path = "spotifagent.infrastructure.entrypoints.cli.commands.users.user_update_logic"
        with mock.patch(target_path, new_callable=mock.AsyncMock) as patched:
            yield patched

    def test__nominal(
        self,
        mock_user_update_logic: mock.AsyncMock,
        runner: CliRunner,
        clean_typer_text: TextCleaner,
    ) -> None:
        user_id = uuid.uuid4()

        result = runner.invoke(app, ["users", "update", str(user_id), "--email", "new@example.com"])
        assert result.exit_code == 0

        output = clean_typer_text(result.stdout)
        assert f"User {user_id} updated successfully!" in output

    def test__no_attribute_to_update(
        self,
        mock_user_update_logic: mock.AsyncMock,
        runner: CliRunner,
        clean_typer_text: TextCleaner,
    ) -> None:
        result = runner.invoke(app, ["users", "update", str(uuid.uuid4())])
        assert result.exit_code != 0

        output = clean_typer_text(result.stderr)
        assert "1 validation error for UserUpdate" in output
        assert "At least one field must be provided for update" in output

    def test__user_not_found(
        self,
        mock_user_update_logic: mock.AsyncMock,
        runner: CliRunner,
        clean_typer_text: TextCleaner,
    ) -> None:
        mock_user_update_logic.side_effect = UserNotFound()
        user_id = uuid.uuid4()

        result = runner.invoke(app, ["users", "update", str(user_id), "--email", "new@example.com"])
        assert result.exit_code != 0

        output = clean_typer_text(result.stderr)
        assert f"User not found with ID {user_id}" in output

    def test__exceptions(
        self,
        mock_user_update_logic: mock.AsyncMock,
        runner: CliRunner,
        clean_typer_text: TextCleaner,
    ) -> None:
        mock_user_update_logic.side_effect = Exception("Boom")

        result = runner.invoke(app, ["users", "update", str(uuid.uuid4()), "--email", "new@example.com"])
        assert result.exit_code != 0

        output = clean_typer_text(result.stderr)
        assert "Error: Boom" in output


@pytest.mark.usefixtures("mock_get_db", "mock_user_repository")
class TestUserUpdateLogic:
    TARGET_PATH: Final[str] = "spotifagent.infrastructure.entrypoints.cli.commands.users.update"

    @pytest.fixture
    def mock_user_update(self) -> Iterable[mock.AsyncMock]:
        with mock.patch(f"{self.TARGET_PATH}.user_update", new_callable=mock.AsyncMock) as patched:
            yield patched

    async def test__user_not_found(
        self,
        mock_user_repository: mock.AsyncMock,
        capsys: pytest.CaptureFixture,
    ) -> None:
        mock_user_repository.get_by_id.return_value = None

        user_id = uuid.uuid4()
        with pytest.raises(UserNotFound):
            await user_update_logic(user_id, UserUpdate(email="new@example.com"))

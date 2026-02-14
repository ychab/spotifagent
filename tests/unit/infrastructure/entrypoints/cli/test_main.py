from typing import get_args
from unittest import mock

import pytest
from typer.testing import CliRunner

from spotifagent import __version__
from spotifagent.infrastructure.entrypoints.cli.main import app
from spotifagent.infrastructure.types import LogLevel

from tests.unit.infrastructure.entrypoints.cli.conftest import TextCleaner


class TestBaseCommand:
    @pytest.mark.parametrize("cmd_arg", ["--version", "-v"])
    def test__version(self, runner: CliRunner, cmd_arg: str, block_cli_configure_loggers: mock.Mock) -> None:
        result = runner.invoke(app, [cmd_arg])

        assert result.exit_code == 0
        assert f"Spotifagent Version: {__version__}" in result.output

        block_cli_configure_loggers.assert_not_called()

    @pytest.mark.parametrize("log_level", get_args(LogLevel))
    def test__log_level(self, runner: CliRunner, block_cli_configure_loggers: mock.Mock, log_level: str) -> None:
        @app.command("noop")
        def noop():
            pass

        result = runner.invoke(app, ["--log-level", "DEBUG", "noop"])
        assert result.exit_code == 0

        block_cli_configure_loggers.assert_called_once_with(
            level="DEBUG",
            handlers=mock.ANY,
        )

    def test__log_handler__nominal(self, runner: CliRunner, block_cli_configure_loggers: mock.Mock) -> None:
        @app.command("noop")
        def noop():
            pass

        result = runner.invoke(app, ["--log-handlers", "console", "--log-handlers", "null", "noop"])
        assert result.exit_code == 0

        block_cli_configure_loggers.assert_called_once_with(
            level=mock.ANY,
            handlers=["console", "null"],
        )

    def test__log_handler__invalid(
        self,
        runner: CliRunner,
        block_cli_configure_loggers: mock.Mock,
        clean_typer_text: TextCleaner,
    ) -> None:
        @app.command("noop")
        def noop():
            pass

        result = runner.invoke(app, ["--log-handlers", "foo", "--log-handlers", "bar", "noop"])
        assert result.exit_code == 2

        output = clean_typer_text(result.output)
        assert "Invalid value for '--log-handlers'" in output
        assert "Invalid handler: '['foo', 'bar']'" in output

        block_cli_configure_loggers.assert_not_called()

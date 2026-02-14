from typing import Literal

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
LogHandler = Literal["console", "cli", "cli_alert", "rich", "null"]

import logging.config
from copy import deepcopy
from typing import Any
from typing import Final

from spotifagent.infrastructure.types import LogHandler
from spotifagent.infrastructure.types import LogLevel

LOGGER_SPOTIFAGENT: Final[str] = "spotifagent"

default_conf: Final[dict[str, Any]] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
        "message": {
            "format": "%(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "level": "DEBUG",
            "formatter": "default",
            "stream": "ext://sys.stdout",
        },
        "cli": {
            "class": "logging.StreamHandler",
            "level": "DEBUG",
            "formatter": "message",
            "stream": "ext://sys.stdout",
        },
        "cli_alert": {
            "class": "logging.StreamHandler",
            "level": "WARNING",
            "formatter": "default",
            "stream": "ext://sys.stdout",
        },
        "null": {
            "class": "logging.NullHandler",
        },
    },
    "loggers": {
        LOGGER_SPOTIFAGENT: {
            "level": "INFO",
            "handlers": ["console"],
            "propagate": False,
        },
        "uvicorn": {
            "level": "INFO",
            "handlers": ["console"],
            "propagate": False,
        },
        "alembic": {
            "level": "INFO",
            "handlers": ["console"],
            "propagate": False,
        },
        "sqlalchemy.engine": {
            "level": "WARNING",
            "handlers": ["console"],
            "propagate": False,
        },
        "httpx": {
            "level": "WARNING",
            "handlers": ["console"],
            "propagate": False,
        },
    },
    "root": {
        "level": "INFO",
        "handlers": ["console"],
    },
}


def configure_loggers(level: LogLevel, handlers: list[LogHandler], propagate: bool = False) -> None:
    conf = deepcopy(default_conf)

    # Change level and propagate only for our logger for now.
    conf["loggers"][LOGGER_SPOTIFAGENT]["level"] = level
    conf["loggers"][LOGGER_SPOTIFAGENT]["propagate"] = propagate

    # However, change handlers for all loggers defined to use the same.
    for logger in conf["loggers"].keys():
        conf["loggers"][logger]["handlers"] = handlers

    # Without forgetting the root handlers.
    conf["root"]["handlers"] = handlers

    logging.config.dictConfig(conf)

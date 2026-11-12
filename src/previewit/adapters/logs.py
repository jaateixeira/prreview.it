"""Logging with loguru, and one place that sets the level.

Levels, from chattiest: TRACE (cache hits, per-request detail), DEBUG, INFO, WARNING, ERROR.
Standard-library loggers (uvicorn, SQLAlchemy, authlib) are routed through loguru.
"""

from __future__ import annotations

import logging
import sys

from loguru import logger

LEVELS = ("TRACE", "DEBUG", "INFO", "WARNING", "ERROR")

FORMAT = (
    "<green>{time:HH:mm:ss.SSS}</green> <level>{level: <7}</level> "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)


class _Intercept(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame, depth = frame.f_back, depth + 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def configure_logging(level: str = "INFO") -> None:
    """Replace loguru's default sink and capture standard logging. Safe to call again."""
    level = level.upper()
    if level not in LEVELS:
        raise ValueError(f"log level must be one of {', '.join(LEVELS)}")
    logger.remove()
    logger.add(
        sys.stderr, level=level, format=FORMAT, colorize=None, backtrace=False, diagnose=False
    )
    logging.basicConfig(handlers=[_Intercept()], level=0, force=True)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lib = logging.getLogger(name)  # uvicorn installs its own handlers and stops propagation
        lib.handlers.clear()
        lib.propagate = True
    for noisy in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING if level != "TRACE" else logging.DEBUG)

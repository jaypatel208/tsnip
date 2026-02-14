"""Centralized logging configuration using Loguru.

Call `configure_logging()` once at startup (in container.py).
All other modules simply do: `from loguru import logger`
— no getLogger(__name__) boilerplate needed.
"""

from __future__ import annotations

import os
import sys

from loguru import logger


def configure_logging(*, level: str | None = None, serialize: bool = False) -> None:
    """Set up loguru with a clean, consistent format.

    Args:
        level: Minimum log level. Falls back to LOG_LEVEL env var, then INFO.
        serialize: If True, output JSON logs (useful for log aggregation in prod).
    """
    resolved_level = level or os.getenv("LOG_LEVEL", "INFO").upper()

    # Remove default loguru handler
    logger.remove()

    # Compact format: timestamp | level | module:function:line | message
    fmt = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )

    logger.add(
        sys.stderr,
        format=fmt,
        level=resolved_level,
        colorize=True,
        serialize=serialize,
        backtrace=True,
        diagnose=False,  # False in prod to avoid leaking local var values
    )

    logger.info("Logging initialized (level={})", resolved_level)

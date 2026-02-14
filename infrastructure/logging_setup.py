"""Centralised logging configuration — called once at startup."""

import logging


def configure_logging(level: int = logging.INFO) -> None:
    """Set up logging for the entire application.

    Uses a single StreamHandler suitable for serverless environments
    (Vercel, AWS Lambda, etc.).
    """
    root = logging.getLogger()

    # Avoid duplicate handlers if called more than once
    if root.handlers:
        return

    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    root.setLevel(level)
    root.addHandler(handler)

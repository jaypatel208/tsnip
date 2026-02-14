"""Centralised application settings — loaded once at startup.

Replaces scattered os.getenv() calls throughout the codebase.
Validates all required vars eagerly so mis-configuration fails fast.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from loguru import logger

from core.exceptions import ConfigurationError


@dataclass(frozen=True)
class Settings:
    """Immutable application configuration."""

    # Supabase
    supabase_url: str
    supabase_api_key: str
    supabase_table: str  # timestamps table
    supabase_yt_table: str  # youtube streams table
    supabase_yt_channel_table: str  # channel config table
    blacklist_yt_channel: str  # blacklist table

    # YouTube
    yt_data_api_key: str
    youtube_client_id: str
    youtube_client_secret: str
    youtube_refresh_token: str

    # Discord
    discord_bot_token: str

    # Application
    tool_used: str
    cron_secret: str
    cron_secret_dc_keep_alive: str

    @staticmethod
    def from_env() -> Settings:
        """Build Settings from environment variables, raising on any missing."""

        def _require(name: str) -> str:
            value = os.getenv(name, "").strip()
            if not value:
                logger.error("Missing required environment variable: {}", name)
                raise ConfigurationError(
                    f"Missing required environment variable: {name}"
                )
            return value

        logger.info("Loading configuration from environment variables")

        settings = Settings(
            supabase_url=_require("SUPABASE_URL"),
            supabase_api_key=_require("SUPABASE_API_KEY"),
            supabase_table=_require("SUPABASE_TABLE"),
            supabase_yt_table=_require("SUPABASE_YT_TABLE"),
            supabase_yt_channel_table=_require("SUPABASE_YT_CHANNEL_TABLE"),
            blacklist_yt_channel=_require("BLACKLIST_YT_CHANNEL"),
            yt_data_api_key=_require("YT_DATA_API_V3"),
            youtube_client_id=_require("YOUTUBE_CLIENT_ID"),
            youtube_client_secret=_require("YOUTUBE_CLIENT_SECRET"),
            youtube_refresh_token=_require("YOUTUBE_REFRESH_TOKEN"),
            discord_bot_token=_require("DISCORD_BOT_TOKEN"),
            tool_used=_require("TOOL_USED"),
            cron_secret=_require("CRON_SECRET"),
            cron_secret_dc_keep_alive=_require("CRON_SECRET_DC_KEEP_ALIVE"),
        )

        logger.info(
            "Configuration loaded — {} env vars validated",
            14,
        )

        return settings

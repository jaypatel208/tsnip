"""Dependency-injection wiring + Flask app factory.

This is the *composition root*: it instantiates concrete implementations,
injects them into services, and registers route blueprints.
"""

from __future__ import annotations

from flask import Flask
from loguru import logger

from dotenv import load_dotenv

from infrastructure.config import Settings
from infrastructure.discord_client import DiscordClient
from infrastructure.logging_setup import configure_logging
from infrastructure.supabase_client import SupabaseClient
from infrastructure.supabase_repository import (
    SupabaseChannelRepository,
    SupabaseStreamRepository,
    SupabaseTimestampRepository,
)
from infrastructure.youtube_api_client import YouTubeApiClient
from routes.clip_routes import create_clip_blueprint
from routes.health_routes import create_health_blueprint
from routes.keepalive_routes import create_keepalive_blueprint
from routes.monitor_routes import create_monitor_blueprint
from services.clip_service import ClipService
from services.stream_monitor_service import StreamMonitorService


def create_app() -> Flask:
    """Build and return the fully-wired Flask application."""
    load_dotenv()

    # -- Logging (must come first) ------------------------------------------
    configure_logging()
    logger.info("Starting application wiring…")

    try:
        # -- Configuration --------------------------------------------------
        settings = Settings.from_env()

        # -- Infrastructure layer -------------------------------------------
        sb_client = SupabaseClient(settings)
        ts_repo = SupabaseTimestampRepository(sb_client, settings)
        stream_repo = SupabaseStreamRepository(sb_client, settings)
        channel_repo = SupabaseChannelRepository(sb_client, settings)
        youtube = YouTubeApiClient(settings)
        discord = DiscordClient(settings)

        logger.debug("Infrastructure layer initialized")

        # -- Service layer --------------------------------------------------
        clip_service = ClipService(
            timestamp_repo=ts_repo,
            stream_repo=stream_repo,
            channel_repo=channel_repo,
            discord=discord,
            youtube=youtube,
            tool_used=settings.tool_used,
        )
        monitor_service = StreamMonitorService(
            stream_repo=stream_repo,
            ts_repo=ts_repo,
            youtube=youtube,
        )

        logger.debug("Service layer initialized")

        # -- Flask app + blueprints -----------------------------------------
        app = Flask(__name__)
        app.register_blueprint(create_health_blueprint())
        app.register_blueprint(create_clip_blueprint(clip_service))
        app.register_blueprint(create_monitor_blueprint(monitor_service, settings))
        app.register_blueprint(create_keepalive_blueprint(discord, settings))

        logger.info("Application ready — 4 blueprints registered")

        return app

    except Exception as exc:
        logger.critical("Application startup failed: {}", exc)
        raise

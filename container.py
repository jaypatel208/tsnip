"""Dependency Injection container — wires everything together.

No DI framework needed: plain Python constructor injection.
create_app() is the single factory function that builds the
fully-configured Flask application.
"""

from __future__ import annotations

from dotenv import load_dotenv
from flask import Flask

from infrastructure.config import Settings
from infrastructure.logging_setup import configure_logging
from infrastructure.supabase_client import SupabaseClient
from infrastructure.supabase_repository import (
    SupabaseChannelRepository,
    SupabaseStreamRepository,
    SupabaseTimestampRepository,
)
from infrastructure.youtube_api_client import YouTubeApiClient
from infrastructure.discord_client import DiscordClient

from services.clip_service import ClipService
from services.stream_monitor_service import StreamMonitorService

from routes.clip_routes import create_clip_blueprint
from routes.monitor_routes import create_monitor_blueprint
from routes.keepalive_routes import create_keepalive_blueprint
from routes.health_routes import create_health_blueprint


def create_app() -> Flask:
    """Build and return a fully-wired Flask application."""

    # 0. Environment & logging
    load_dotenv()
    configure_logging()

    # 1. Configuration — single parse, validated eagerly
    settings = Settings.from_env()

    # 2. Infrastructure
    sb_client = SupabaseClient(settings)
    ts_repo = SupabaseTimestampRepository(sb_client, settings)
    stream_repo = SupabaseStreamRepository(sb_client, settings)
    channel_repo = SupabaseChannelRepository(sb_client, settings)
    youtube = YouTubeApiClient(settings)
    discord = DiscordClient(settings)

    # 3. Services
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

    # 4. Flask app + blueprints
    app = Flask(__name__)
    app.register_blueprint(create_clip_blueprint(clip_service))
    app.register_blueprint(
        create_monitor_blueprint(monitor_service, settings.cron_secret)
    )
    app.register_blueprint(
        create_keepalive_blueprint(discord, settings.cron_secret_dc_keep_alive)
    )
    app.register_blueprint(create_health_blueprint())

    return app

"""Discord notification client implementation.

Implements core.interfaces.DiscordNotifier.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import requests
from loguru import logger

from core.interfaces import DiscordNotifier
from infrastructure.config import Settings
from services.timestamp_formatter import timestamp_to_seconds


class DiscordClient(DiscordNotifier):
    """Sends embed notifications and keepalive pings via the Discord Bot API."""

    DISCORD_API = "https://discord.com/api/v10"

    def __init__(self, settings: Settings) -> None:
        self._token = settings.discord_bot_token
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bot {self._token}",
                "Content-Type": "application/json",
            }
        )
        self._timeout = 10
        logger.debug("DiscordClient initialized")

    # -- DiscordNotifier interface ------------------------------------------

    def send_clip_notification(
        self,
        discord_channel_id: str,
        video_id: str,
        video_title: str,
        message: str,
        username: str,
        timestamp: Optional[str] = None,
    ) -> bool:
        if not video_id:
            logger.warning("No video_id for Discord notification — skipping.")
            return False
        if not timestamp:
            logger.warning("No timestamp for Discord notification — skipping.")
            return False

        youtube_url = self._build_youtube_url(video_id, timestamp)
        embed = self._build_embed(
            video_id, video_title, message, username, timestamp, youtube_url
        )

        try:
            logger.info(
                "Sending Discord notification → channel={}, video={}, user={}",
                discord_channel_id,
                video_id,
                username,
            )
            resp = self._session.post(
                f"{self.DISCORD_API}/channels/{discord_channel_id}/messages",
                json={"embeds": [embed]},
                timeout=self._timeout,
            )
            if resp.status_code == 200:
                logger.success(
                    "Discord notification sent to channel {}", discord_channel_id
                )
                return True
            logger.error(
                "Discord notification failed (status={}): {}",
                resp.status_code,
                resp.text,
            )
            return False
        except Exception as exc:
            logger.exception("Error sending Discord notification: {}", exc)
            return False

    def keepalive_ping(self) -> dict:
        start = datetime.now()
        try:
            logger.debug("Sending Discord keepalive ping")
            resp = self._session.get(
                f"{self.DISCORD_API}/users/@me", timeout=self._timeout
            )
            elapsed_ms = round((datetime.now() - start).total_seconds() * 1000, 2)

            if resp.status_code == 200:
                bot = resp.json()
                logger.info(
                    "Keepalive OK — bot={}, response_time={}ms",
                    bot.get("username"),
                    elapsed_ms,
                )
                return {
                    "status": "success",
                    "message": "Discord bot keepalive successful",
                    "bot_username": bot.get("username"),
                    "bot_discriminator": bot.get("discriminator"),
                    "response_time_ms": elapsed_ms,
                    "timestamp": datetime.now().isoformat(),
                }
            logger.warning("Discord API returned status {}", resp.status_code)
            return {
                "status": "warning",
                "message": f"Discord API returned {resp.status_code}",
                "response_code": resp.status_code,
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as exc:
            logger.exception("Keepalive failed: {}", exc)
            return {
                "status": "error",
                "message": "Keepalive failed",
                "timestamp": datetime.now().isoformat(),
            }

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _build_youtube_url(video_id: str, timestamp: str) -> str:
        seconds = timestamp_to_seconds(timestamp)
        return f"https://www.youtube.com/watch?v={video_id}&t={seconds}s"

    @staticmethod
    def _build_embed(
        video_id: str,
        video_title: str,
        message: str,
        username: str,
        timestamp: str,
        youtube_url: str,
    ) -> dict:
        return {
            "title": message.strip() or "📎 New Clip Created",
            "url": youtube_url,
            "color": 0xFF0000,
            "image": {
                "url": f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
            },
            "fields": [
                {"name": "🎬 Stream", "value": video_title, "inline": False},
                {"name": "👤 Created by", "value": username, "inline": True},
                {"name": "⏰ Timestamp", "value": timestamp, "inline": True},
            ],
            "footer": {"text": "Tsnip • Click title to watch at this moment"},
        }

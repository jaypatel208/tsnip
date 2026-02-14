"""Supabase-backed repository implementations.

Implements TimestampRepository, StreamRepository, and ChannelRepository
from core.interfaces using the shared SupabaseClient.
"""

from __future__ import annotations

import logging
from typing import Optional

from core.entities import (
    ChatMessage,
    CommentTemplate,
    LiveStreamInfo,
    StreamInfo,
    UnmarkedStream,
)
from core.constants import DEFAULT_COMMENT_TEMPLATE
from core.interfaces import ChannelRepository, StreamRepository, TimestampRepository
from infrastructure.config import Settings
from infrastructure.supabase_client import SupabaseClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TimestampRepository
# ---------------------------------------------------------------------------


class SupabaseTimestampRepository(TimestampRepository):
    """CRUD for the timestamps (ts_db) table."""

    def __init__(self, client: SupabaseClient, settings: Settings) -> None:
        self._client = client
        self._table = settings.supabase_table

    def insert_clip(
        self,
        channel_id: str,
        chat_id: str,
        delay: int,
        message: str,
        user_name: str,
        user_timestamp: str,
    ) -> bool:
        data = {
            "channel_id": channel_id,
            "chat_id": chat_id,
            "user_timestamp": user_timestamp,
            "delay": delay,
            "message": message,
            "user_name": user_name,
        }
        try:
            resp = self._client.post(self._table, data)
            if resp.status_code != 201:
                logger.error("Supabase insert failed: %s", resp.text)
                return False
            return True
        except Exception as exc:
            logger.error("Error in insert_clip: %s", exc)
            return False

    def get_chat_messages(self, chat_id: str) -> list[ChatMessage]:
        try:
            rows = self._client.get(
                self._table,
                f"chat_id=eq.{chat_id}&select=message,user_name,user_timestamp,delay",
            )
            return [
                ChatMessage(
                    message=r.get("message", ""),
                    user_name=r["user_name"],
                    user_timestamp=r["user_timestamp"],
                    delay=r["delay"],
                )
                for r in rows
            ]
        except Exception as exc:
            logger.error("Error fetching chat messages for %s: %s", chat_id, exc)
            return []


# ---------------------------------------------------------------------------
# StreamRepository
# ---------------------------------------------------------------------------


class SupabaseStreamRepository(StreamRepository):
    """CRUD for the YouTube streams (yt_db) table."""

    def __init__(self, client: SupabaseClient, settings: Settings) -> None:
        self._client = client
        self._table = settings.supabase_yt_table

    def chat_id_exists(self, chat_id: str) -> bool:
        try:
            rows = self._client.get(
                self._table,
                f"chat_id=eq.{chat_id}&select=chat_id&limit=1",
                timeout=10,
            )
            return len(rows) > 0
        except Exception as exc:
            logger.error("Error checking chat_id %s: %s", chat_id, exc)
            return False

    def get_live_stream_info(self, channel_id: str) -> LiveStreamInfo:
        try:
            rows = self._client.get(
                self._table,
                f"channel_id=eq.{channel_id}&status=eq.live&limit=1",
                timeout=10,
            )
            if rows:
                return LiveStreamInfo(
                    video_id=rows[0].get("video_id"),
                    title=rows[0].get("title", "Live Stream"),
                    stream_start_time=rows[0].get("stream_start_time"),
                )
        except Exception as exc:
            logger.error("Error fetching live stream info: %s", exc)

        return LiveStreamInfo()

    def get_unmarked_streams(self) -> list[UnmarkedStream]:
        try:
            rows = self._client.get(
                self._table,
                "marked=eq.false&select=video_id,id,chat_id,channel_id,stream_start_time",
            )
            return [
                UnmarkedStream(
                    id=r["id"],
                    video_id=r["video_id"],
                    chat_id=r["chat_id"],
                    channel_id=r["channel_id"],
                    stream_start_time=r.get("stream_start_time"),
                )
                for r in rows
            ]
        except Exception as exc:
            logger.error("Error fetching unmarked streams: %s", exc)
            return []

    def stream_exists(self, chat_id: str, video_id: str) -> bool:
        try:
            rows = self._client.get(
                self._table,
                f"chat_id=eq.{chat_id}&video_id=eq.{video_id}",
            )
            return len(rows) > 0
        except Exception as exc:
            logger.error("Error checking stream %s: %s", video_id, exc)
            return False

    def insert_streams(self, chat_id: str, streams: list[StreamInfo]) -> bool:
        new_records = []
        for s in streams:
            if not self.stream_exists(chat_id, s.video_id):
                record: dict = {
                    "chat_id": chat_id,
                    "video_id": s.video_id,
                    "title": s.title,
                    "status": s.status,
                    "url": s.url,
                    "channel": s.channel,
                    "channel_id": s.channel_id,
                    "marked": False,
                }
                if s.start_time:
                    record["stream_start_time"] = s.start_time
                new_records.append(record)
            else:
                logger.info("Stream %s already exists, skipping.", s.video_id)

        if not new_records:
            logger.info("No new streams to insert for chat_id %s.", chat_id)
            return True

        try:
            resp = self._client.post(self._table, new_records)
            if resp.status_code == 201:
                logger.info("✓ Inserted %d new stream records.", len(new_records))
                return True
            logger.error("✗ Stream insert failed: %s", resp.text)
            return False
        except Exception as exc:
            logger.error("✗ Error inserting streams: %s", exc)
            return False

    def mark_as_processed(
        self, row_id: str, success: bool = True, status: str = "ended"
    ) -> bool:
        try:
            resp = self._client.patch(
                self._table,
                f"id=eq.{row_id}",
                {"marked": success, "status": status},
            )
            resp.raise_for_status()
            logger.info("Database updated for row %s → %s", row_id, status)
            return True
        except Exception as exc:
            logger.error("Error updating row %s: %s", row_id, exc)
            return False


# ---------------------------------------------------------------------------
# ChannelRepository
# ---------------------------------------------------------------------------


class SupabaseChannelRepository(ChannelRepository):
    """Read access to the channel configuration (yt_channel_db) table."""

    def __init__(self, client: SupabaseClient, settings: Settings) -> None:
        self._client = client
        self._channel_table = settings.supabase_yt_channel_table
        self._blacklist_table = settings.blacklist_yt_channel

    def get_discord_channel_id(self, channel_id: str) -> Optional[str]:
        try:
            rows = self._client.get(
                self._channel_table,
                f"channel_id=eq.{channel_id}&select=dc_channel_id",
                timeout=10,
            )
            if rows and rows[0].get("dc_channel_id"):
                return rows[0]["dc_channel_id"]
        except Exception as exc:
            logger.error("Error fetching Discord channel ID: %s", exc)
        return None

    def get_comment_template(self, channel_id: str) -> CommentTemplate:
        try:
            rows = self._client.get(
                self._channel_table,
                f"channel_id=eq.{channel_id}&select=channel_template",
                timeout=10,
            )
            if rows and rows[0].get("channel_template"):
                return CommentTemplate(
                    template=rows[0]["channel_template"], is_custom=True
                )
        except Exception as exc:
            logger.error("Error fetching template: %s", exc)

        return CommentTemplate(template=DEFAULT_COMMENT_TEMPLATE, is_custom=False)

    def is_blacklisted(self, channel_id: str) -> bool:
        try:
            rows = self._client.get(
                self._blacklist_table,
                f"channel_id=eq.{channel_id}&select=id",
                timeout=10,
            )
            return len(rows) > 0
        except Exception as exc:
            logger.error("Error checking blacklist for %s: %s", channel_id, exc)
            return False

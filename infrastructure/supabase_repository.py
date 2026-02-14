"""Supabase-backed repository implementations.

Implements TimestampRepository, StreamRepository, and ChannelRepository
from core.interfaces using the shared SupabaseClient.
"""

from __future__ import annotations

from typing import Optional

import requests
from loguru import logger

from core.constants import DEFAULT_COMMENT_TEMPLATE
from core.entities import (
    ChatMessage,
    CommentTemplate,
    LiveStreamInfo,
    StreamInfo,
    UnmarkedStream,
)
from core.interfaces import ChannelRepository, StreamRepository, TimestampRepository
from infrastructure.config import Settings
from infrastructure.supabase_client import SupabaseClient


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
                logger.error(
                    "Supabase insert failed (status={}): {}",
                    resp.status_code,
                    resp.text,
                )
                return False
            logger.info(
                "Clip saved — user={}, channel={}, delay={}s",
                user_name,
                channel_id,
                delay,
            )
            return True
        except Exception as exc:
            logger.exception("Error in insert_clip: {}", exc)
            return False

    def get_chat_messages(self, chat_id: str) -> list[ChatMessage]:
        try:
            rows = self._client.get(
                self._table,
                f"chat_id=eq.{chat_id}&select=message,user_name,user_timestamp,delay",
            )
            logger.debug("Fetched {} messages for chat_id={}", len(rows), chat_id)
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
            logger.exception("Error fetching chat messages for {}: {}", chat_id, exc)
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
            exists = len(rows) > 0
            logger.debug("chat_id_exists({}) → {}", chat_id, exists)
            return exists
        except Exception as exc:
            logger.exception("Error checking chat_id {}: {}", chat_id, exc)
            return False

    def get_live_stream_info(self, channel_id: str) -> LiveStreamInfo:
        try:
            rows = self._client.get(
                self._table,
                f"channel_id=eq.{channel_id}&status=eq.live&limit=1",
                timeout=10,
            )
            if rows:
                info = LiveStreamInfo(
                    video_id=rows[0].get("video_id"),
                    title=rows[0].get("title", "Live Stream"),
                    stream_start_time=rows[0].get("stream_start_time"),
                )
                logger.debug(
                    "Live stream found for {} → {}",
                    channel_id,
                    info.video_id,
                )
                return info
        except Exception as exc:
            logger.exception("Error fetching live stream info: {}", exc)

        logger.debug("No live stream found for channel {}", channel_id)
        return LiveStreamInfo()

    def get_unmarked_streams(self) -> list[UnmarkedStream]:
        try:
            rows = self._client.get(
                self._table,
                "marked=eq.false&select=video_id,id,chat_id,channel_id,stream_start_time",
            )
            result = [
                UnmarkedStream(
                    id=r["id"],
                    video_id=r["video_id"],
                    chat_id=r["chat_id"],
                    channel_id=r["channel_id"],
                    stream_start_time=r.get("stream_start_time"),
                )
                for r in rows
            ]
            logger.info("Found {} unmarked streams", len(result))
            return result
        except Exception as exc:
            logger.exception("Error fetching unmarked streams: {}", exc)
            return []

    def stream_exists(self, chat_id: str, video_id: str) -> bool:
        try:
            rows = self._client.get(
                self._table,
                f"chat_id=eq.{chat_id}&video_id=eq.{video_id}",
            )
            return len(rows) > 0
        except Exception as exc:
            logger.exception("Error checking stream {}: {}", video_id, exc)
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
                logger.debug("Stream {} already exists, skipping.", s.video_id)

        if not new_records:
            logger.info("No new streams to insert for chat_id {}.", chat_id)
            return True

        try:
            resp = self._client.post(self._table, new_records)
            if resp.status_code == 201:
                logger.info("✓ Inserted {} new stream records.", len(new_records))
                return True
            logger.error(
                "✗ Stream insert failed (status={}): {}", resp.status_code, resp.text
            )
            return False
        except Exception as exc:
            logger.exception("✗ Error inserting streams: {}", exc)
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
            logger.info("Database updated for row {} → {}", row_id, status)
            return True
        except requests.HTTPError as exc:
            logger.error(
                "HTTP error updating row {} — status={}: {}",
                row_id,
                exc.response.status_code if exc.response is not None else "?",
                exc.response.text[:200] if exc.response is not None else "?",
            )
            return False
        except Exception as exc:
            logger.exception("Error updating row {}: {}", row_id, exc)
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
                dc_id = rows[0]["dc_channel_id"]
                logger.debug("Discord channel for {} → {}", channel_id, dc_id)
                return dc_id
        except Exception as exc:
            logger.exception("Error fetching Discord channel ID: {}", exc)
        return None

    def get_comment_template(self, channel_id: str) -> CommentTemplate:
        try:
            rows = self._client.get(
                self._channel_table,
                f"channel_id=eq.{channel_id}&select=channel_template",
                timeout=10,
            )
            if rows and rows[0].get("channel_template"):
                logger.debug("Custom template found for {}", channel_id)
                return CommentTemplate(
                    template=rows[0]["channel_template"], is_custom=True
                )
        except Exception as exc:
            logger.exception("Error fetching template: {}", exc)

        return CommentTemplate(template=DEFAULT_COMMENT_TEMPLATE, is_custom=False)

    def is_blacklisted(self, channel_id: str) -> bool:
        try:
            rows = self._client.get(
                self._blacklist_table,
                f"channel_id=eq.{channel_id}&select=id",
                timeout=10,
            )
            blacklisted = len(rows) > 0
            if blacklisted:
                logger.warning("Channel {} is blacklisted", channel_id)
            return blacklisted
        except Exception as exc:
            logger.exception("Error checking blacklist for {}: {}", channel_id, exc)
            return False

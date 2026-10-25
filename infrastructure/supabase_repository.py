"""Supabase-backed implementation of core.interfaces.Repository.

Tables and functions are defined in supabase/migrations/.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import requests
from loguru import logger

from core.entities import ChatMessage, ClipContext, QueuedStream, Video
from core.exceptions import ExternalServiceError, ValidationError
from core.interfaces import Repository
from infrastructure.supabase_client import SupabaseClient


class SupabaseRepository(Repository):
    def __init__(self, client: SupabaseClient) -> None:
        self._client = client

    def record_timestamp(
        self, chat_id: str, channel_id: str, user: str, message: str, delay: int
    ) -> ClipContext:
        try:
            row = self._client.rpc(
                "record_timestamp",
                {
                    "p_chat_id": chat_id,
                    "p_channel_id": channel_id,
                    "p_user": user,
                    "p_message": message,
                    "p_delay": delay,
                },
            )
        except requests.HTTPError as exc:
            # PostgREST answers 400 for the function's own refusals (a chat id
            # with no video in it) and for check violations.
            if exc.response is not None and exc.response.status_code == 400:
                raise ValidationError("Invalid chat_id") from exc
            raise ExternalServiceError("Failed to save timestamp") from exc
        except requests.RequestException as exc:
            raise ExternalServiceError("Failed to save timestamp") from exc
        logger.info("Timestamp saved — user={}, video={}", user, row["video_id"])
        return ClipContext(**row)

    def save_stream(self, video: Video) -> Optional[str]:
        try:
            return self._client.rpc(
                "save_stream",
                {
                    "p_video_id": video.video_id,
                    "p_channel_id": video.channel_id,
                    "p_channel_title": video.channel_title,
                    "p_title": video.title,
                    "p_started_at": video.started_at,
                },
            )
        except requests.RequestException as exc:
            logger.error("Error saving stream {}: {}", video.video_id, exc)
            return None

    def get_queue(self) -> list[QueuedStream]:
        try:
            rows = self._client.get(
                "streams",
                {
                    "state": "in.(new,pending)",
                    "select": "video_id,state,created_at,channel_id,started_at",
                    "order": "created_at.asc",
                },
            )
        except requests.RequestException as exc:
            logger.error("Error fetching queued streams: {}", exc)
            return []
        logger.info("Found {} queued streams", len(rows))
        return [QueuedStream(**r) for r in rows]

    def get_messages(self, video_id: str) -> list[ChatMessage]:
        try:
            rows = self._client.get(
                "timestamps",
                {
                    "video_id": f"eq.{video_id}",
                    "select": "message,user_name,created_at,delay",
                    "order": "created_at.asc",
                },
            )
        except requests.RequestException as exc:
            logger.error("Error fetching messages for {}: {}", video_id, exc)
            return []
        return [ChatMessage(**r) for r in rows]

    def claim(self, video_id: str) -> bool:
        try:
            rows = self._client.patch(
                "streams",
                {"video_id": f"eq.{video_id}", "state": "eq.pending"},
                {"state": "posting"},
            )
        except requests.RequestException as exc:
            logger.error("Error claiming {}: {}", video_id, exc)
            return False
        return bool(rows)

    def finish(
        self, video_id: str, state: str, comment_id: Optional[str] = None
    ) -> bool:
        try:
            self._client.patch(
                "streams",
                {"video_id": f"eq.{video_id}"},
                {
                    "state": state,
                    "comment_id": comment_id,
                    "processed_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        except requests.RequestException as exc:
            logger.error("Error saving {} as {}: {}", video_id, state, exc)
            return False
        logger.info("Stream {} → {}", video_id, state)
        return True

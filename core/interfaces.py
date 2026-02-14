"""Domain interfaces (ports) — abstract contracts for infrastructure.

All services depend on these ABCs, never on concrete implementations.
This enforces the Dependency Inversion Principle (DIP).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from core.entities import (
    ChatMessage,
    CommentTemplate,
    LiveStreamInfo,
    StreamInfo,
    UnmarkedStream,
    VideoStatus,
)


# ---------------------------------------------------------------------------
# Repository interfaces (data access)
# ---------------------------------------------------------------------------


class TimestampRepository(ABC):
    """Read/write access to the timestamps table."""

    @abstractmethod
    def insert_clip(
        self,
        channel_id: str,
        chat_id: str,
        delay: int,
        message: str,
        user_name: str,
        user_timestamp: str,
    ) -> bool: ...

    @abstractmethod
    def get_chat_messages(self, chat_id: str) -> list[ChatMessage]: ...


class StreamRepository(ABC):
    """Read/write access to the YouTube streams table."""

    @abstractmethod
    def chat_id_exists(self, chat_id: str) -> bool: ...

    @abstractmethod
    def get_live_stream_info(self, channel_id: str) -> LiveStreamInfo: ...

    @abstractmethod
    def get_unmarked_streams(self) -> list[UnmarkedStream]: ...

    @abstractmethod
    def stream_exists(self, chat_id: str, video_id: str) -> bool: ...

    @abstractmethod
    def insert_streams(self, chat_id: str, streams: list[StreamInfo]) -> bool: ...

    @abstractmethod
    def mark_as_processed(
        self, row_id: str, success: bool = True, status: str = "ended"
    ) -> bool: ...


class ChannelRepository(ABC):
    """Read access to the channel configuration table."""

    @abstractmethod
    def get_discord_channel_id(self, channel_id: str) -> Optional[str]: ...

    @abstractmethod
    def get_comment_template(self, channel_id: str) -> CommentTemplate: ...

    @abstractmethod
    def is_blacklisted(self, channel_id: str) -> bool: ...


# ---------------------------------------------------------------------------
# External service interfaces
# ---------------------------------------------------------------------------


class YouTubeClient(ABC):
    """Interface for YouTube Data API + OAuth operations."""

    @abstractmethod
    def get_live_streams(
        self, channel_id: str, max_results: int = 5
    ) -> list[StreamInfo]: ...

    @abstractmethod
    def check_video_status(self, video_id: str) -> VideoStatus: ...

    @abstractmethod
    def post_comment(self, video_id: str, comment_body: str) -> bool | str: ...


class DiscordNotifier(ABC):
    """Interface for sending Discord notifications."""

    @abstractmethod
    def send_clip_notification(
        self,
        discord_channel_id: str,
        video_id: str,
        video_title: str,
        message: str,
        username: str,
        timestamp: Optional[str] = None,
    ) -> bool: ...

    @abstractmethod
    def keepalive_ping(self) -> dict: ...

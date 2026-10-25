"""Domain interfaces (ports) — abstract contracts for infrastructure.

All services depend on these ABCs, never on concrete implementations.
This enforces the Dependency Inversion Principle (DIP).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from core.entities import ChatMessage, ClipContext, QueuedStream, Video


# ---------------------------------------------------------------------------
# Repository interface (data access)
# ---------------------------------------------------------------------------


class Repository(ABC):
    """Read/write access to channels, streams and timestamps."""

    @abstractmethod
    def record_timestamp(
        self, chat_id: str, channel_id: str, user: str, message: str, delay: int
    ) -> ClipContext:
        """Save a !ts. Raises ValidationError for a chat id with no video in
        it, ExternalServiceError when the database fails."""

    @abstractmethod
    def save_stream(self, video: Video) -> Optional[str]:
        """Store what YouTube says about a stream; returns its state."""

    @abstractmethod
    def get_queue(self) -> list[QueuedStream]: ...

    @abstractmethod
    def get_messages(self, video_id: str) -> list[ChatMessage]: ...

    @abstractmethod
    def claim(self, video_id: str) -> bool:
        """Move a pending stream to 'posting'; False if it isn't pending."""

    @abstractmethod
    def finish(
        self, video_id: str, state: str, comment_id: Optional[str] = None
    ) -> bool: ...


# ---------------------------------------------------------------------------
# External service interfaces
# ---------------------------------------------------------------------------


class YouTubeClient(ABC):
    """Interface for YouTube Data API + OAuth operations."""

    @abstractmethod
    def get_videos(self, video_ids: list[str]) -> Optional[dict[str, Video]]:
        """Look up to 50 videos in one call; None if the API call failed."""

    @abstractmethod
    def is_member_only(self, video_id: str) -> bool: ...

    @abstractmethod
    def post_comment(self, video_id: str, comment_body: str) -> tuple[str, str]:
        """Returns (outcome, detail). Outcome is one of:
        "posted" (detail: comment id), "rejected" (detail: the stream state),
        "failed" (nothing was posted), or "unknown" (it may have been)."""


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

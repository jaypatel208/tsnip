"""Domain entities — pure data carriers with no business logic.

All entities are frozen dataclasses to enforce immutability and
make them safe to share across layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Clip domain
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClipRequest:
    """Incoming clip creation request (validated at the route boundary)."""

    user: str
    channel_id: str
    chat_id: str
    delay: int
    message: str = ""
    user_timestamp: str = ""  # ISO-8601 UTC set by the service layer


@dataclass(frozen=True)
class CommentTemplate:
    """A channel's comment template + whether it's custom or the default."""

    template: str
    is_custom: bool


# ---------------------------------------------------------------------------
# YouTube / Stream domain
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StreamInfo:
    """Represents a YouTube live/completed stream."""

    video_id: str
    title: str
    status: str  # "live" | "completed" | "ended" | "member_only"
    url: str
    channel: str
    channel_id: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None


@dataclass(frozen=True)
class LiveStreamInfo:
    """Minimal live-stream data used during clip creation."""

    video_id: Optional[str] = None
    title: str = "Live Stream"
    stream_start_time: Optional[str] = None


@dataclass(frozen=True)
class VideoStatus:
    """Result of checking whether a video is commentable."""

    can_comment: bool = False
    is_member_only: bool = False
    is_public: bool = False
    is_unlisted: bool = False
    comments_disabled: bool = True
    is_live: bool = False
    live_status: str = ""


# ---------------------------------------------------------------------------
# Chat / Timestamp domain
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChatMessage:
    """A single timestamped chat message from the database."""

    message: str
    user_name: str
    user_timestamp: str
    delay: int


@dataclass(frozen=True)
class UnmarkedStream:
    """A stream row that hasn't been processed for comment posting yet."""

    id: str  # Supabase row UUID
    video_id: str
    chat_id: str
    channel_id: str
    stream_start_time: Optional[str] = None

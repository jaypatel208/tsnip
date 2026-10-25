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


@dataclass(frozen=True)
class ClipContext:
    """What a saved !ts returns: its stream and the requesting channel's settings."""

    video_id: str
    created_at: str  # when the timestamp was saved (ISO-8601)
    title: Optional[str] = None
    started_at: Optional[str] = None
    owner_id: Optional[str] = None  # the stream's channel, once YouTube confirmed it
    template: Optional[str] = None  # None → the default template
    dc_channel_id: Optional[str] = None


# ---------------------------------------------------------------------------
# YouTube / Stream domain
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Video:
    """One video as the YouTube Data API reports it."""

    video_id: str
    title: str
    channel_id: str
    channel_title: str
    started_at: Optional[str] = None
    is_live: bool = False  # live, upcoming, or started and not ended
    visible: bool = False  # public or unlisted
    made_for_kids: bool = False  # YouTube turns comments off for these


@dataclass(frozen=True)
class QueuedStream:
    """A stream waiting for its timestamps comment."""

    video_id: str
    state: str  # "new" (not checked on YouTube yet) | "pending"
    created_at: str
    channel_id: Optional[str] = None
    started_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Chat / Timestamp domain
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChatMessage:
    """A single saved !ts."""

    message: str
    user_name: str
    created_at: str
    delay: int

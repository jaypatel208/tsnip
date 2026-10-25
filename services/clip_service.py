"""Clip creation use-case.

Orchestrates: save (one DB round trip) → Discord notify → build the chat reply.
All dependencies are injected via constructor (DIP).
"""

from __future__ import annotations

import re

from loguru import logger

from core.constants import CHAT_MAX_LENGTH, DEFAULT_COMMENT_TEMPLATE
from core.entities import ClipContext, ClipRequest
from core.interfaces import DiscordNotifier, Repository, YouTubeClient
from services.timestamp_formatter import format_timestamp

# Pre-compiled regex for channel ID validation
_CHANNEL_ID_RE = re.compile(r"^UC[a-zA-Z0-9_-]{22}$")
_PLACEHOLDER_VALUES = frozenset(
    {"$(user)", "$(chatid)", "$(channelid)", "$(querystring)"}
)


class ClipService:
    """Application service for the clip-creation flow."""

    def __init__(
        self,
        repo: Repository,
        discord: DiscordNotifier,
        youtube: YouTubeClient,
        tool_used: str,
    ) -> None:
        self._repo = repo
        self._discord = discord
        self._yt = youtube
        self._tool_used = tool_used

    # -- public API ---------------------------------------------------------

    def create_clip(self, req: ClipRequest) -> str:
        """Save the timestamp, notify Discord, and return the chat reply.

        Raises:
            ValidationError: the chat id carries no video id (caller → 400).
            ExternalServiceError: the database failed (caller → 500).
        """
        logger.info(
            "Creating clip — user={}, channel={}, delay={}s, msg='{}'",
            req.user,
            req.channel_id,
            req.delay,
            req.message[:50],
        )
        # The database links the chat to its own stream, so this one call
        # replaces the old insert + lookups. YouTube checks the stream later,
        # in the monitor, off Nightbot's clock.
        ctx = self._repo.record_timestamp(
            req.chat_id, req.channel_id, req.user, req.message, req.delay
        )

        # Finished before we reply: work left running after the response is
        # lost on Vercel (see 28ef3e4).
        if ctx.dc_channel_id:
            try:
                self._send_discord_notification(req, ctx)
            except Exception as exc:
                logger.exception("Discord notification failed: {}", exc)

        logger.success("Clip created for user={}", req.user)
        return self._build_comment(ctx.template, req.user, req.delay, req.message)

    # -- validation helpers (static, used by routes) -------------------------

    @staticmethod
    def validate_chat_id(chat_id: str) -> bool:
        return isinstance(chat_id, str) and 22 <= len(chat_id) <= 200

    @staticmethod
    def validate_channel_id(channel_id: str) -> bool:
        return bool(channel_id) and bool(_CHANNEL_ID_RE.fullmatch(channel_id))

    @staticmethod
    def has_placeholder(value: str) -> bool:
        return str(value) in _PLACEHOLDER_VALUES

    # -- internal -----------------------------------------------------------

    def _send_discord_notification(self, req: ClipRequest, ctx: ClipContext) -> None:
        title, started_at, owner = ctx.title, ctx.started_at, ctx.owner_id
        if not started_at:
            # First !ts of this stream (or it hadn't started): ask YouTube.
            video = (self._yt.get_videos([ctx.video_id]) or {}).get(ctx.video_id)
            if video:
                self._repo.save_stream(video)
                title, started_at, owner = (
                    video.title,
                    video.started_at,
                    video.channel_id,
                )

        # A request naming another channel must not post this stream into
        # that channel's Discord.
        if owner != req.channel_id:
            logger.warning("{} is not {}'s stream.", ctx.video_id, req.channel_id)
            return
        if not started_at:
            logger.debug("{} hasn't started — no Discord timestamp.", ctx.video_id)
            return

        self._discord.send_clip_notification(
            ctx.dc_channel_id,
            ctx.video_id,
            title or "Live Stream",
            req.message,
            req.user.lstrip("@") or "Unknown",
            format_timestamp(started_at, ctx.created_at, req.delay),
        )

    def _build_comment(
        self, template: str | None, user: str, delay: int, message: str
    ) -> str:
        try:
            return self._fill(
                template or DEFAULT_COMMENT_TEMPLATE, user, delay, message
            )
        except (KeyError, IndexError, ValueError) as exc:
            logger.error(
                "Failed to format comment template — "
                "template may contain invalid placeholders: {}",
                exc,
            )
            # Fallback: return a safe default comment
            return self._fill(DEFAULT_COMMENT_TEMPLATE, user, delay, message)

    def _fill(self, template: str, user: str, delay: int, message: str) -> str:
        """Fill *template*, shortening only the title so the line fits YouTube
        chat and the link at its end is never cut off."""

        def fill(title: str) -> str:
            title_part = f" — titled '{title}'" if title else ""
            return template.format(
                user=user, delay=delay, title_part=title_part, tool_used=self._tool_used
            )

        line = fill(message)
        over = len(line) - CHAT_MAX_LENGTH
        if over > 0 and message:
            line = fill(message[: max(len(message) - over - 1, 0)] + "…")
        return line

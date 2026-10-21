"""Clip creation use-case.

Orchestrates: validate → save to DB → YouTube processing → Discord notify → build comment.
All dependencies are injected via constructor (DIP).
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from loguru import logger

from core.constants import CHAT_MAX_LENGTH, DEFAULT_COMMENT_TEMPLATE
from core.entities import ClipRequest
from core.interfaces import (
    ChannelRepository,
    DiscordNotifier,
    StreamRepository,
    TimestampRepository,
    YouTubeClient,
)
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
        timestamp_repo: TimestampRepository,
        stream_repo: StreamRepository,
        channel_repo: ChannelRepository,
        discord: DiscordNotifier,
        youtube: YouTubeClient,
        tool_used: str,
    ) -> None:
        self._ts_repo = timestamp_repo
        self._stream_repo = stream_repo
        self._channel_repo = channel_repo
        self._discord = discord
        self._yt = youtube
        self._tool_used = tool_used

    # -- public API ---------------------------------------------------------

    def create_clip(self, req: ClipRequest) -> str:
        """Execute the full clip-creation flow.

        Returns the comment text to send back to the user.

        Raises:
            RuntimeError: on DB failure (caller converts to 500).
        """
        logger.info(
            "Creating clip — user={}, channel={}, delay={}s, msg='{}'",
            req.user,
            req.channel_id,
            req.delay,
            req.message[:50] if req.message else "",
        )
        user_timestamp = datetime.now(timezone.utc).isoformat()

        # 1. Persist — this is the critical path, must succeed
        if not self._ts_repo.insert_clip(
            req.channel_id,
            req.chat_id,
            req.delay,
            req.message,
            req.user,
            user_timestamp,
        ):
            logger.error("Failed to save clip for user={}", req.user)
            raise RuntimeError("Failed to save timestamp to database")

        # 2–4 are independent network calls, so they run side by side and
        # Nightbot waits for the slowest instead of the sum. All of them
        # finish before we reply: work left running after the response is
        # lost on Vercel (see 28ef3e4).
        with ThreadPoolExecutor(max_workers=3) as pool:
            # 2. YouTube processing (if needed)
            youtube = pool.submit(
                self._maybe_process_youtube, req.chat_id, req.channel_id
            )
            # 3. Discord notification (best-effort)
            discord = pool.submit(
                self._send_discord_notification,
                req.channel_id,
                req.message,
                req.user,
                user_timestamp,
                req.delay,
            )
            # 4. Build response comment
            built = pool.submit(
                self._build_comment, req.channel_id, req.user, req.delay, req.message
            )
            youtube.result()
            discord.result()
            comment = built.result()

        logger.success("Clip created for user={}", req.user)
        return comment

    # -- validation helpers (static, used by routes) -------------------------

    @staticmethod
    def validate_chat_id(chat_id: str) -> bool:
        return bool(chat_id) and isinstance(chat_id, str) and len(chat_id) >= 22

    @staticmethod
    def validate_channel_id(channel_id: str) -> bool:
        return bool(channel_id) and bool(_CHANNEL_ID_RE.fullmatch(channel_id))

    @staticmethod
    def has_placeholder(value: str) -> bool:
        return str(value) in _PLACEHOLDER_VALUES

    # -- internal -----------------------------------------------------------

    def _maybe_process_youtube(self, chat_id: str, channel_id: str) -> None:
        if self._stream_repo.chat_id_exists(chat_id):
            logger.debug("Chat ID {} already exists, skipping YT processing.", chat_id)
            return

        logger.info("Chat ID {} not found — attempting YouTube processing.", chat_id)
        if self._channel_repo.is_blacklisted(channel_id):
            logger.warning("Skipping blacklisted channel {}.", channel_id)
            return

        try:
            streams = self._yt.get_live_streams(channel_id)
            if streams:
                self._stream_repo.insert_streams(chat_id, streams)
                logger.info("YouTube processing completed for {}.", channel_id)
            else:
                logger.warning("No streams found for channel {}.", channel_id)
        except Exception as exc:
            logger.exception("Error during YouTube processing: {}", exc)

    def _send_discord_notification(
        self,
        channel_id: str,
        message: str,
        user: str,
        user_timestamp: str,
        delay: int,
    ) -> None:
        dc_channel = self._channel_repo.get_discord_channel_id(channel_id)
        if not dc_channel:
            logger.debug("No Discord integration for channel {}.", channel_id)
            return

        info = self._stream_repo.get_live_stream_info(channel_id)
        timestamp = None
        if info.video_id and info.stream_start_time:
            timestamp = format_timestamp(info.stream_start_time, user_timestamp, delay)

        clean_user = user.lstrip("@") if user else "Unknown"
        self._discord.send_clip_notification(
            dc_channel,
            info.video_id or "",
            info.title,
            message,
            clean_user,
            timestamp,
        )

    def _build_comment(
        self, channel_id: str, user: str, delay: int, message: str
    ) -> str:
        tpl = self._channel_repo.get_comment_template(channel_id)
        try:
            return self._fill(tpl.template, user, delay, message)
        except (KeyError, IndexError, ValueError) as exc:
            logger.error(
                "Failed to format comment template for channel {} — "
                "template may contain invalid placeholders: {}",
                channel_id,
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

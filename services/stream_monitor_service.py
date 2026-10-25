"""Stream monitor use-case — processes ended streams and posts comments.

Replaces the handler() + process_single_video() logic from the old
monitor_streams.py. All dependencies are injected.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from loguru import logger

from core.constants import COMMENT_FOOTER, YOUTUBE_COMMENT_MAX_LENGTH
from core.interfaces import StreamRepository, TimestampRepository, YouTubeClient
from services.clip_service import video_id_from_chat
from services.timestamp_formatter import (
    _parse_iso,
    format_timestamp,
    remove_at_symbol,
    remove_custom_emojis,
)

# A stream that still can't be commented this long after it started is
# taken out of the queue, so it stops costing YouTube calls on every run.
GIVE_UP_AFTER = timedelta(hours=48)


class StreamMonitorService:
    """Iterates over unmarked streams, builds comments, posts them."""

    def __init__(
        self,
        stream_repo: StreamRepository,
        ts_repo: TimestampRepository,
        youtube: YouTubeClient,
    ) -> None:
        self._stream_repo = stream_repo
        self._ts_repo = ts_repo
        self._yt = youtube

    def run(self) -> None:
        """Main entry point — called by the cron route."""
        streams = self._stream_repo.get_unmarked_streams()
        if not streams:
            logger.info("No unmarked streams found.")
            return

        logger.info("Processing {} unmarked streams", len(streams))
        processed = failed = 0

        for i, stream in enumerate(streams, 1):
            if self._process_single(stream, i, len(streams)):
                processed += 1
            else:
                failed += 1

        logger.info(
            "Stream monitoring done — processed={}, failed={}", processed, failed
        )

    # -- internal -----------------------------------------------------------

    def _process_single(self, stream, idx: int, total: int) -> bool:
        try:
            logger.info("[{}/{}] Processing video={}", idx, total, stream.video_id)

            # Rows from before chats were linked to their own stream only:
            # this chat's timestamps belong to another video, never post them.
            if video_id_from_chat(stream.chat_id) != stream.video_id:
                self._stream_repo.mark_as_processed(
                    stream.id, success=True, status="wrong_link"
                )
                logger.warning("{} linked to another stream's chat.", stream.video_id)
                return True

            status = self._yt.check_video_status(stream.video_id)

            if status.is_live:
                logger.info("{} still live — skipping.", stream.video_id)
                return False

            if status.is_member_only:
                self._stream_repo.mark_as_processed(
                    stream.id, success=True, status="member_only"
                )
                logger.info("Skipped member-only {}.", stream.video_id)
                return True

            # Unavailable (private, deleted, or API returned empty data). It
            # may be a passing API error, so retry until GIVE_UP_AFTER.
            if not status.is_public and not status.is_unlisted and not status.is_live:
                return self._give_up_if_stale(stream, "unavailable")

            if not status.can_comment:
                return self._give_up_if_stale(stream, "not_commentable")

            # Build comment body
            messages = self._ts_repo.get_chat_messages(stream.chat_id)
            if not messages:
                logger.warning("No messages for chat {}.", stream.chat_id)
                return self._give_up_if_stale(stream, "no_timestamps")

            lines = self._format_lines(messages, stream.stream_start_time)
            if not lines:
                logger.warning("No formatted lines for {}.", stream.video_id)
                return self._give_up_if_stale(stream, "no_timestamps")

            body = "Time stamps:\n\n" + "\n".join(lines) + "\n\n" + COMMENT_FOOTER
            body = _truncate(body)

            logger.debug(
                "Comment for {} — {} lines, {} chars",
                stream.video_id,
                len(lines),
                len(body),
            )

            result = self._yt.post_comment(stream.video_id, body)

            if result is True:
                self._stream_repo.mark_as_processed(stream.id)
                logger.success("✓ Processed {}.", stream.video_id)
                return True

            if result == "member_only":
                self._stream_repo.mark_as_processed(
                    stream.id, success=True, status="member_only"
                )
                logger.info(
                    "{} marked as member_only after comment attempt.", stream.video_id
                )
                return True

            # post_comment returned False — could be transient (auth error,
            # quota, etc.). Do NOT mark the stream — it can be retried on
            # the next cron run after a manual token refresh.
            logger.error("✗ Failed to post comment for {}.", stream.video_id)
            return False

        except Exception as exc:
            logger.exception("Error processing {}: {}", stream.video_id, exc)
            return False

    def _give_up_if_stale(self, stream, status: str) -> bool:
        """Take *stream* out of the queue with *status* once it started more
        than GIVE_UP_AFTER ago; until then leave it for the next run. A
        stream with no start time is kept, as before."""
        try:
            started = _parse_iso(stream.stream_start_time)
        except (TypeError, ValueError, AttributeError):
            started = None
        if started is None or datetime.now(timezone.utc) - started < GIVE_UP_AFTER:
            logger.warning("{} {} — retrying next run.", stream.video_id, status)
            return False

        self._stream_repo.mark_as_processed(stream.id, success=True, status=status)
        logger.warning(
            "{} {} after {} — given up.", stream.video_id, status, GIVE_UP_AFTER
        )
        return True

    @staticmethod
    def _format_lines(messages, start_time: str | None) -> list[str]:
        if not start_time:
            return []

        lines: list[str] = []
        for m in messages:
            try:
                ts = format_timestamp(start_time, m.user_timestamp, m.delay)
                msg = remove_custom_emojis(m.message.strip())
                user = remove_at_symbol(m.user_name)

                if msg:
                    lines.append(f"{ts} – _{msg}_ (by {user})")
                else:
                    lines.append(f"{ts} – (by {user})")
            except Exception as exc:
                logger.error("Error formatting message: {}", exc)
        return lines


def _truncate(body: str, max_len: int = YOUTUBE_COMMENT_MAX_LENGTH) -> str:
    """Truncate comment if it exceeds YouTube's character limit."""
    if len(body) <= max_len:
        return body

    cut = body[: max_len - 100 - len(COMMENT_FOOTER)]
    last_nl = cut.rfind("\n")
    if last_nl > 0:
        cut = cut[:last_nl]
    cut += "\n\n[Comment truncated due to length limit]\n\n" + COMMENT_FOOTER
    logger.warning("Comment truncated from {} to {} chars.", len(body), len(cut))
    return cut

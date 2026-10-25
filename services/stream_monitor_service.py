"""Stream monitor use-case — comments each ended stream's timestamps on it.

Each run checks the queued streams on YouTube (50 per call), and for every
one that has ended, claims it, posts its comment once, and records the
outcome. All dependencies are injected.
"""

from __future__ import annotations

import dataclasses
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from loguru import logger

from core.constants import COMMENT_FOOTER, YOUTUBE_COMMENT_MAX_LENGTH
from core.entities import QueuedStream, Video
from core.interfaces import Repository, YouTubeClient
from services.timestamp_formatter import (
    _parse_iso,
    comment_lines,
    offset_seconds,
    remove_at_symbol,
    remove_custom_emojis,
)

# A stream that still can't be commented this long after it started is
# taken out of the queue, so it stops costing YouTube calls on every run.
GIVE_UP_AFTER = timedelta(hours=48)
# Vercel stops the function at 300s; stop starting new streams before that.
TIME_BUDGET_SECONDS = 240
# videos.list takes up to 50 ids for the same 1 quota unit.
BATCH_SIZE = 50


class StreamMonitorService:
    """Iterates over queued streams, builds comments, posts them."""

    def __init__(
        self,
        repo: Repository,
        youtube: YouTubeClient,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._repo = repo
        self._yt = youtube
        self._clock = clock

    def run(self) -> None:
        """Main entry point — called by the cron route."""
        streams = self._repo.get_queue()
        if not streams:
            logger.info("No queued streams found.")
            return

        logger.info("Processing {} queued streams", len(streams))
        deadline = self._clock() + TIME_BUDGET_SECONDS
        done = 0

        for i in range(0, len(streams), BATCH_SIZE):
            batch = streams[i : i + BATCH_SIZE]
            videos = self._yt.get_videos([s.video_id for s in batch])
            if videos is None:
                # A failed API call says nothing about the streams; don't let
                # it count towards giving up on them.
                logger.error("YouTube lookup failed — batch left for next run.")
                continue
            for stream in batch:
                if self._clock() > deadline:
                    logger.warning(
                        "Time budget spent — {} streams left for next run.",
                        len(streams) - done,
                    )
                    return
                self._process_single(stream, videos.get(stream.video_id))
                done += 1

        logger.info("Stream monitoring done — {} streams checked", done)

    # -- internal -----------------------------------------------------------

    def _process_single(self, stream: QueuedStream, video: Optional[Video]) -> bool:
        try:
            logger.info("Processing video={}", stream.video_id)

            # Private, deleted, or not a video at all. It may come back, so
            # retry until GIVE_UP_AFTER.
            if video is None:
                return self._give_up_if_stale(stream, "unavailable")

            # First look at this stream, or its start time was unknown: store
            # what YouTube says (its owner decides blacklisting).
            if stream.state == "new" or not stream.started_at:
                if self._repo.save_stream(video) == "blacklisted":
                    logger.warning("Skipped {}: blacklisted channel.", stream.video_id)
                    return True
                stream = dataclasses.replace(
                    stream,
                    state="pending",
                    started_at=video.started_at or stream.started_at,
                )

            if video.is_live:
                logger.info("{} still live — skipping.", stream.video_id)
                return False

            if not video.visible:
                return self._give_up_if_stale(stream, "unavailable")

            if video.made_for_kids:
                return self._give_up_if_stale(stream, "not_commentable")

            if self._yt.is_member_only(stream.video_id):
                self._repo.finish(stream.video_id, "member_only")
                logger.info("Skipped member-only {}.", stream.video_id)
                return True

            lines = self._format_lines(
                self._repo.get_messages(stream.video_id), stream.started_at
            )
            if not lines:
                logger.warning("No timestamps to post for {}.", stream.video_id)
                return self._give_up_if_stale(stream, "no_timestamps")

            body = "Time stamps:\n\n" + "\n".join(lines) + "\n\n" + COMMENT_FOOTER
            body = _truncate(body)

            # Claim it first, so a second monitor run can never post it too.
            if not self._repo.claim(stream.video_id):
                logger.warning("{} claimed elsewhere — skipping.", stream.video_id)
                return False

            outcome, detail = self._yt.post_comment(stream.video_id, body)

            if outcome == "posted":
                self._repo.finish(stream.video_id, "posted", comment_id=detail)
                logger.success("✓ Processed {}.", stream.video_id)
                return True

            if outcome == "rejected":
                self._repo.finish(stream.video_id, detail)
                logger.info("{} rejected the comment: {}.", stream.video_id, detail)
                return True

            if outcome == "failed":
                # Nothing was posted (quota, auth): put it back for next run.
                self._repo.finish(stream.video_id, "pending")
                logger.error("✗ Failed to post comment for {}.", stream.video_id)
                return False

            # The request went out but we don't know whether YouTube took it.
            # Retrying could post it twice, so it stays 'posting' for a person
            # to check the video and set 'posted' or 'pending'.
            logger.critical(
                "{} may or may not have its comment — left as 'posting': {}",
                stream.video_id,
                detail,
            )
            return False

        except Exception as exc:
            logger.exception("Error processing {}: {}", stream.video_id, exc)
            return False

    def _give_up_if_stale(self, stream: QueuedStream, status: str) -> bool:
        """Take *stream* out of the queue with *status* once it started (or,
        if it never did, was first timestamped) more than GIVE_UP_AFTER ago;
        until then leave it for the next run."""
        try:
            since = _parse_iso(stream.started_at or stream.created_at)
        except (TypeError, ValueError, AttributeError):
            since = None
        if since is None or datetime.now(timezone.utc) - since < GIVE_UP_AFTER:
            logger.warning("{} {} — retrying next run.", stream.video_id, status)
            return False

        self._repo.finish(stream.video_id, status)
        logger.warning(
            "{} {} after {} — given up.", stream.video_id, status, GIVE_UP_AFTER
        )
        return True

    @staticmethod
    def _format_lines(messages, start_time: str | None) -> list[str]:
        if not start_time:
            return []

        entries = []
        for m in messages:
            try:
                entries.append(
                    (
                        offset_seconds(start_time, m.created_at, m.delay),
                        remove_custom_emojis(m.message.strip()).strip(),
                        remove_at_symbol(m.user_name),
                    )
                )
            except Exception as exc:
                logger.error("Error formatting message: {}", exc)
        return comment_lines(entries)


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

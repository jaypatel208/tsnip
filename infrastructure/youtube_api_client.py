"""YouTube Data API + OAuth client implementation.

Implements core.interfaces.YouTubeClient. Handles:
- Searching for live/completed streams via the Data API
- Checking video status (public, member-only, live, etc.)
- Posting comments via OAuth with retry logic
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Optional

import requests
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from core.entities import StreamInfo, VideoStatus
from core.interfaces import YouTubeClient
from infrastructure.config import Settings

logger = logging.getLogger(__name__)

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"


class YouTubeApiClient(YouTubeClient):
    """Concrete YouTube client backed by the Data API v3 + OAuth."""

    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.yt_data_api_key
        self._client_id = settings.youtube_client_id
        self._client_secret = settings.youtube_client_secret
        self._refresh_token = settings.youtube_refresh_token
        self._session = requests.Session()
        self._timeout = 30

    # -- YouTubeClient interface --------------------------------------------

    def get_live_streams(
        self, channel_id: str, max_results: int = 5
    ) -> list[StreamInfo]:
        """Search for live, then completed streams for *channel_id*."""
        try:
            channel_name = self._get_channel_name(channel_id)
        except Exception:
            return []

        for event_type in ("live", "completed"):
            streams = self._search_streams(
                channel_id, channel_name, event_type, max_results
            )
            if streams:
                return streams

        return []

    def check_video_status(self, video_id: str) -> VideoStatus:
        """Check if a video is public, live, member-only, etc."""
        try:
            params = {
                "part": "status,statistics,snippet,liveStreamingDetails",
                "id": video_id,
                "key": self._api_key,
            }
            resp = self._session.get(
                f"{YOUTUBE_API_BASE}/videos",
                params=params,
                timeout=self._timeout,
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])

            if not items:
                logger.warning("No video data for %s", video_id)
                return VideoStatus()

            return self._parse_video_status(items[0], video_id)

        except Exception as exc:
            logger.error("Error checking video status for %s: %s", video_id, exc)
            return VideoStatus()

    def post_comment(
        self, video_id: str, comment_body: str, max_retries: int = 3, delay: int = 60
    ) -> bool | str:
        """Post a comment with retry logic. Returns True, False, or 'member_only'."""
        for attempt in range(max_retries):
            try:
                logger.info(
                    "Posting comment to %s (attempt %d/%d)",
                    video_id,
                    attempt + 1,
                    max_retries,
                )

                status = self.check_video_status(video_id)

                if status.is_member_only:
                    logger.info("%s is member-only — skipping.", video_id)
                    return "member_only"

                if not status.can_comment:
                    logger.warning("%s not ready for comments.", video_id)
                    if attempt < max_retries - 1:
                        time.sleep(delay)
                    continue

                yt = self._get_authenticated_client()
                yt.commentThreads().insert(
                    part="snippet",
                    body={
                        "snippet": {
                            "videoId": video_id,
                            "topLevelComment": {
                                "snippet": {"textOriginal": comment_body}
                            },
                        }
                    },
                ).execute()

                logger.info("Comment posted to %s.", video_id)
                return True

            except Exception as exc:
                error_msg = str(exc).lower()
                logger.error("Attempt %d failed for %s: %s", attempt + 1, video_id, exc)

                if any(
                    kw in error_msg
                    for kw in (
                        "commentsdisabled",
                        "forbidden",
                        "insufficientpermissions",
                        "channelsubscriptionrequired",
                    )
                ):
                    return "member_only"
                if "quotaexceeded" in error_msg:
                    logger.error("YouTube API quota exceeded.")
                    return False

                if attempt < max_retries - 1:
                    time.sleep(delay)

        return False

    # -- internal helpers ---------------------------------------------------

    def _get_channel_name(self, channel_id: str) -> str:
        params = {"part": "snippet", "id": channel_id, "key": self._api_key}
        resp = self._session.get(
            f"{YOUTUBE_API_BASE}/channels",
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if not items:
            raise ValueError(f"Channel {channel_id} not found")
        return items[0]["snippet"]["title"]

    def _search_streams(
        self,
        channel_id: str,
        channel_name: str,
        event_type: str,
        max_results: int,
    ) -> list[StreamInfo]:
        try:
            params = {
                "part": "snippet",
                "channelId": channel_id,
                "type": "video",
                "eventType": event_type,
                "key": self._api_key,
                "maxResults": max_results,
                "order": "date",
            }
            resp = self._session.get(
                f"{YOUTUBE_API_BASE}/search",
                params=params,
                timeout=10,
            )
            resp.raise_for_status()
            videos = resp.json().get("items", [])

            if not videos:
                return []

            timing = self._batch_streaming_details([v["id"]["videoId"] for v in videos])

            streams: list[StreamInfo] = []
            for v in videos:
                vid = v["id"]["videoId"]
                t = timing.get(vid, {})
                streams.append(
                    StreamInfo(
                        video_id=vid,
                        title=v["snippet"]["title"],
                        status=event_type,
                        url=f"https://www.youtube.com/watch?v={vid}",
                        channel=channel_name,
                        channel_id=channel_id,
                        start_time=t.get("start_time"),
                        end_time=t.get("end_time"),
                    )
                )
            logger.info("Found %d %s streams.", len(streams), event_type)
            return streams

        except Exception as exc:
            logger.error("Error searching %s streams: %s", event_type, exc)
            return []

    def _batch_streaming_details(
        self, video_ids: list[str]
    ) -> dict[str, dict[str, Optional[str]]]:
        if not video_ids:
            return {}
        try:
            params = {
                "part": "liveStreamingDetails",
                "id": ",".join(video_ids),
                "key": self._api_key,
            }
            resp = self._session.get(
                f"{YOUTUBE_API_BASE}/videos",
                params=params,
                timeout=10,
            )
            resp.raise_for_status()
            result: dict[str, dict[str, Optional[str]]] = {}
            for item in resp.json().get("items", []):
                details = item.get("liveStreamingDetails", {})
                result[item["id"]] = {
                    "start_time": details.get("actualStartTime"),
                    "end_time": details.get("actualEndTime"),
                }
            return result
        except Exception as exc:
            logger.error("Error getting streaming details: %s", exc)
            return {}

    def _parse_video_status(self, video_data: dict, video_id: str) -> VideoStatus:
        status = video_data.get("status", {})
        snippet = video_data.get("snippet", {})
        live_details = video_data.get("liveStreamingDetails", {})

        privacy = status.get("privacyStatus", "")
        is_public = privacy == "public"
        is_unlisted = privacy == "unlisted"
        comments_disabled = status.get("madeForKids", False)

        # Live broadcast check
        broadcast = snippet.get("liveBroadcastContent", "none")
        if broadcast in ("live", "upcoming"):
            logger.info("%s is %s — skipping.", video_id, broadcast)
            return VideoStatus(
                is_public=is_public,
                is_unlisted=is_unlisted,
                is_live=True,
                live_status=broadcast,
                comments_disabled=False,
            )

        # Started but not ended → still live
        if live_details.get("actualStartTime") and not live_details.get(
            "actualEndTime"
        ):
            logger.info("%s is currently live (no end time).", video_id)
            return VideoStatus(
                is_public=is_public,
                is_unlisted=is_unlisted,
                is_live=True,
                live_status="live",
                comments_disabled=False,
            )

        is_member_only = self._check_member_only(video_id)
        can_comment = (
            (is_public or is_unlisted) and not comments_disabled and not is_member_only
        )

        logger.info(
            "%s — public=%s unlisted=%s disabled=%s member=%s",
            video_id,
            is_public,
            is_unlisted,
            comments_disabled,
            is_member_only,
        )

        return VideoStatus(
            can_comment=can_comment,
            is_member_only=is_member_only,
            is_public=is_public,
            is_unlisted=is_unlisted,
            comments_disabled=comments_disabled,
        )

    def _check_member_only(self, video_id: str) -> bool:
        """Scrape the YouTube page to detect member-only badges."""
        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/91.0.4472.124 Safari/537.36"
                )
            }
            resp = self._session.get(
                f"https://www.youtube.com/watch?v={video_id}",
                headers=headers,
                timeout=30,
            )
            resp.raise_for_status()

            match = re.search(r"var ytInitialData = ({.*?});", resp.text)
            if not match:
                return False

            data = json.loads(match.group(1))
            contents = (
                data.get("contents", {})
                .get("twoColumnWatchNextResults", {})
                .get("results", {})
                .get("results", {})
                .get("contents", [])
            )

            for item in contents:
                renderer = item.get("videoPrimaryInfoRenderer", {})
                for badge in renderer.get("badges", []):
                    br = badge.get("metadataBadgeRenderer", {})
                    label = br.get("label", "").lower()
                    style = br.get("style", "")
                    if "member" in label or "BADGE_STYLE_TYPE_MEMBERS_ONLY" in style:
                        logger.info("%s detected as member-only.", video_id)
                        return True

            return False

        except Exception as exc:
            logger.error("Error checking member-only for %s: %s", video_id, exc)
            return False

    def _get_authenticated_client(self):
        creds = Credentials(
            None,
            refresh_token=self._refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self._client_id,
            client_secret=self._client_secret,
            scopes=["https://www.googleapis.com/auth/youtube.force-ssl"],
        )
        creds.refresh(GoogleAuthRequest())
        return build("youtube", "v3", credentials=creds, cache_discovery=False)

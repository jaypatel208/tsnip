"""YouTube Data API + OAuth client implementation.

Implements core.interfaces.YouTubeClient. Handles:
- Looking up videos (owner, start time, live, privacy) via the Data API
- Detecting member-only streams
- Posting comments via OAuth, at most once
"""

from __future__ import annotations

import json
import re
import time
from typing import Optional

import requests
from loguru import logger
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from core.entities import Video
from core.interfaces import YouTubeClient
from infrastructure.config import Settings

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"


class YouTubeApiClient(YouTubeClient):
    """Concrete YouTube client backed by the Data API v3 + OAuth."""

    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.yt_data_api_key
        self._client_id = settings.youtube_client_id
        self._client_secret = settings.youtube_client_secret
        self._refresh_token = settings.youtube_refresh_token
        self._session = requests.Session()
        # Retry transient network errors automatically
        retry = Retry(
            total=2,
            backoff_factor=0.3,
            status_forcelist=[502, 503, 504],
            allowed_methods=["GET", "POST"],
        )
        self._session.mount("https://", HTTPAdapter(max_retries=retry))
        self._timeout = 15
        # Caches
        self._member_only_cache: dict[str, bool] = {}
        self._yt_client = None  # Cached authenticated client
        self._yt_client_expiry: float = 0  # Epoch timestamp
        logger.debug("YouTubeApiClient initialized")

    # -- YouTubeClient interface --------------------------------------------

    def get_videos(self, video_ids: list[str]) -> Optional[dict[str, Video]]:
        """Look up to 50 videos in one call (1 quota unit, whatever the count)."""
        try:
            resp = self._session.get(
                f"{YOUTUBE_API_BASE}/videos",
                params={
                    "part": "snippet,status,liveStreamingDetails",
                    "id": ",".join(video_ids),
                    "maxResults": 50,
                    "key": self._api_key,
                },
                timeout=self._timeout,
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
        except Exception as exc:
            logger.exception("Error fetching videos {}: {}", video_ids, exc)
            return None
        return {item["id"]: _to_video(item) for item in items}

    def post_comment(self, video_id: str, comment_body: str) -> tuple[str, str]:
        """Post *comment_body* once. Nothing is retried after the request went
        out: if YouTube may have taken it, a retry could post it twice."""
        # Imported here, not at the top: only the comment cron needs it.
        from googleapiclient.errors import HttpError

        try:
            yt = self._get_authenticated_client()
        except Exception:
            return "failed", "oauth"

        logger.info("Posting comment to {}", video_id)
        try:
            resp = (
                yt.commentThreads()
                .insert(
                    part="snippet",
                    body={
                        "snippet": {
                            "videoId": video_id,
                            "topLevelComment": {
                                "snippet": {"textOriginal": comment_body}
                            },
                        }
                    },
                )
                .execute()
            )
        except HttpError as exc:
            # The reasons live in error_details; str(exc) only shows them
            # when the error carries the request URI.
            error = f"{exc.error_details} {exc}".lower()
            if exc.resp.status >= 500:
                return "unknown", error
            if "quotaexceeded" in error:
                logger.critical("YouTube API quota exceeded!")
                return "failed", "quota"
            if "commentsdisabled" in error:
                return "rejected", "not_commentable"
            if any(
                kw in error
                for kw in (
                    "forbidden",
                    "insufficientpermissions",
                    "channelsubscriptionrequired",
                )
            ):
                return "rejected", "member_only"
            return "failed", error
        except Exception as exc:  # timeout, dropped connection: may have posted
            return "unknown", str(exc)

        logger.success("Comment posted to {}.", video_id)
        return "posted", resp.get("id", "")

    # -- internal helpers ---------------------------------------------------

    def is_member_only(self, video_id: str) -> bool:
        """Scrape the YouTube page to detect member-only badges.

        Results are cached in-memory for the lifetime of this client
        instance (member-only status doesn't change mid-cron-run).
        """
        if video_id in self._member_only_cache:
            return self._member_only_cache[video_id]

        result = False
        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            }
            resp = self._session.get(
                f"https://www.youtube.com/watch?v={video_id}",
                headers=headers,
                timeout=8,
            )
            resp.raise_for_status()

            match = re.search(r"var ytInitialData = ({.*?});", resp.text)
            if not match:
                self._member_only_cache[video_id] = False
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
                        logger.info("{} detected as member-only.", video_id)
                        result = True
                        break
                if result:
                    break

        except requests.Timeout:
            logger.warning(
                "Timeout checking member-only for {} — assuming not.", video_id
            )
        except Exception as exc:
            logger.warning("Error checking member-only for {}: {}", video_id, exc)

        self._member_only_cache[video_id] = result
        return result

    def _get_authenticated_client(self):
        """Return a cached YouTube API client, refreshing credentials only when expired."""
        now = time.time()
        if self._yt_client and now < self._yt_client_expiry:
            return self._yt_client

        logger.debug("Refreshing YouTube OAuth credentials")
        # Imported here, not at the top: only the comment cron needs them, and
        # they are heavy enough to slow every cold `!ts` reply.
        from google.auth.transport.requests import Request as GoogleAuthRequest
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        try:
            creds = Credentials(
                None,
                refresh_token=self._refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=self._client_id,
                client_secret=self._client_secret,
                scopes=["https://www.googleapis.com/auth/youtube.force-ssl"],
            )
            creds.refresh(GoogleAuthRequest())
            self._yt_client = build(
                "youtube", "v3", credentials=creds, cache_discovery=False
            )
            # Cache for 50 minutes (tokens typically last 60 min)
            self._yt_client_expiry = now + 3000
            logger.debug("OAuth credentials refreshed and cached")
            return self._yt_client
        except Exception as exc:
            # Clear cache on failure so next call retries
            self._yt_client = None
            self._yt_client_expiry = 0
            logger.error(
                "OAuth credential refresh failed — check YOUTUBE_CLIENT_ID, "
                "YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN: {}",
                type(exc).__name__,
            )
            raise


def _to_video(item: dict) -> Video:
    snippet = item.get("snippet", {})
    status = item.get("status", {})
    details = item.get("liveStreamingDetails", {})
    started = details.get("actualStartTime")
    return Video(
        video_id=item["id"],
        title=snippet.get("title", ""),
        channel_id=snippet.get("channelId", ""),
        channel_title=snippet.get("channelTitle", ""),
        started_at=started,
        is_live=snippet.get("liveBroadcastContent") in ("live", "upcoming")
        or bool(started and not details.get("actualEndTime")),
        visible=status.get("privacyStatus") in ("public", "unlisted"),
        made_for_kids=bool(status.get("madeForKids")),
    )

import os
import requests
import time
import re
import logging
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_API_KEY = os.getenv("SUPABASE_API_KEY")
SUPABASE_YT_TABLE = os.getenv("SUPABASE_YT_TABLE")
SUPABASE_TABLE = os.getenv("SUPABASE_TABLE")
YT_DATA_API_V3 = os.getenv("YT_DATA_API_V3")
YOUTUBE_CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID")
YOUTUBE_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET")
YOUTUBE_REFRESH_TOKEN = os.getenv("YOUTUBE_REFRESH_TOKEN")

# YouTube comment character limit (conservative estimate)
YOUTUBE_COMMENT_MAX_LENGTH = 9000


def validate_environment():
    """Validate that all required environment variables are set"""
    required_vars = [
        "SUPABASE_URL",
        "SUPABASE_API_KEY",
        "SUPABASE_YT_TABLE",
        "SUPABASE_TABLE",
        "YT_DATA_API_V3",
        "YOUTUBE_CLIENT_ID",
        "YOUTUBE_CLIENT_SECRET",
        "YOUTUBE_REFRESH_TOKEN",
    ]

    missing_vars = [var for var in required_vars if not os.getenv(var)]

    if missing_vars:
        logger.error(
            f"Missing required environment variables: {', '.join(missing_vars)}"
        )
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing_vars)}"
        )

    logger.info("All required environment variables are set")


def get_youtube_client():
    """Get authenticated YouTube client with error handling"""
    try:
        creds = Credentials(
            None,
            refresh_token=YOUTUBE_REFRESH_TOKEN,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=YOUTUBE_CLIENT_ID,
            client_secret=YOUTUBE_CLIENT_SECRET,
            scopes=["https://www.googleapis.com/auth/youtube.force-ssl"],
        )
        creds.refresh(Request())
        client = build("youtube", "v3", credentials=creds, cache_discovery=False)
        logger.info("YouTube client authenticated successfully")
        return client
    except Exception as e:
        logger.error(f"Failed to authenticate YouTube client: {e}")
        raise


def get_unmarked_streams():
    """Get unmarked streams from Supabase with error handling"""
    try:
        url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_YT_TABLE}?marked=eq.false&select=video_id,id,chat_id,channel_id,stream_start_time"
        headers = {
            "apikey": SUPABASE_API_KEY,
            "Authorization": f"Bearer {SUPABASE_API_KEY}",
        }

        logger.info("Fetching unmarked streams from Supabase")
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()

        data = resp.json()
        logger.info(f"Retrieved {len(data)} unmarked streams")
        return data

    except requests.exceptions.RequestException as e:
        logger.error(f"Request error while fetching unmarked streams: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error while fetching unmarked streams: {e}")
        return []


def get_chat_messages(chat_id):
    """Get chat messages from Supabase with error handling"""
    try:
        url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}?chat_id=eq.{chat_id}&select=message,user_name,user_timestamp,delay"
        headers = {
            "apikey": SUPABASE_API_KEY,
            "Authorization": f"Bearer {SUPABASE_API_KEY}",
        }

        logger.info(f"Fetching chat messages for chat_id: {chat_id}")
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()

        data = resp.json()
        logger.info(f"Retrieved {len(data)} chat messages for chat_id: {chat_id}")
        return data

    except requests.exceptions.RequestException as e:
        logger.error(f"Request error while fetching chat messages for {chat_id}: {e}")
        return []
    except Exception as e:
        logger.error(
            f"Unexpected error while fetching chat messages for {chat_id}: {e}"
        )
        return []


def format_timestamp(start_time_str, user_time_str, delay):
    """Format timestamp for display"""
    try:
        # Force UTC timezone-aware parsing
        start_time = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        else:
            start_time = start_time.astimezone(timezone.utc)

        user_time = datetime.fromisoformat(user_time_str)
        if user_time.tzinfo is None:
            user_time = user_time.replace(tzinfo=timezone.utc)
        else:
            user_time = user_time.astimezone(timezone.utc)

        adjusted_user_time = user_time - timedelta(seconds=delay)
        delta = adjusted_user_time - start_time
        total_seconds = max(0, int(delta.total_seconds()))  # avoid negatives
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return (
            f"{hours:02}:{minutes:02}:{seconds:02}"
            if hours
            else f"{minutes:02}:{seconds:02}"
        )
    except Exception as e:
        logger.error(f"Error formatting timestamp: {e}")
        return "00:00"


def is_video_ready_for_comments(video_id):
    """Check if video is public and ready for comments, including member-only detection"""
    try:
        url = f"https://www.googleapis.com/youtube/v3/videos?part=status,statistics,snippet&id={video_id}&key={YT_DATA_API_V3}"
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()

        data = resp.json()
        items = data.get("items", [])

        if not items:
            logger.warning(f"No video data found for video_id: {video_id}")
            return {
                "can_comment": False,
                "is_member_only": False,
                "is_public": False,
                "comments_disabled": True,
            }

        video_data = items[0]
        status = video_data.get("status", {})
        snippet = video_data.get("snippet", {})

        is_public = status.get("privacyStatus") == "public"
        comments_disabled = status.get("madeForKids", False)

        # Check for member-only video indicators
        title = snippet.get("title", "").lower()
        description = snippet.get("description", "").lower()

        # Common indicators of member-only content
        member_indicators = [
            "members only",
            "member only",
            "members-only",
            "member-only",
            "membership",
            "members stream",
            "member stream",
        ]

        is_member_only = any(
            indicator in title or indicator in description
            for indicator in member_indicators
        )

        logger.info(
            f"Video {video_id} - Public: {is_public}, Comments disabled: {comments_disabled}, Member-only: {is_member_only}"
        )

        return {
            "can_comment": is_public and not comments_disabled and not is_member_only,
            "is_member_only": is_member_only,
            "is_public": is_public,
            "comments_disabled": comments_disabled,
        }

    except requests.exceptions.RequestException as e:
        logger.error(f"Request error checking video status for {video_id}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error checking video status for {video_id}: {e}")

    return {
        "can_comment": False,
        "is_member_only": False,
        "is_public": False,
        "comments_disabled": True,
    }


def post_comment_with_retry(video_id, comment_body, max_retries=3, delay=60):
    """Post comment with retry logic and proper error handling"""
    for attempt in range(max_retries):
        try:
            logger.info(
                f"Attempting to post comment to video {video_id} (attempt {attempt + 1}/{max_retries})"
            )

            # Check if video is ready for comments
            video_status = is_video_ready_for_comments(video_id)

            if video_status["is_member_only"]:
                logger.info(
                    f"Video {video_id} is member-only - skipping comment but marking as processed"
                )
                return "member_only"

            if not video_status["can_comment"]:
                logger.warning(f"Video {video_id} not ready for comments yet")
                if attempt < max_retries - 1:
                    logger.info(f"Waiting {delay} seconds before retry...")
                    time.sleep(delay)
                continue

            yt = get_youtube_client()
            result = (
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

            logger.info(f"Comment posted successfully to video {video_id}")
            return True

        except Exception as e:
            error_msg = str(e)
            logger.error(
                f"Attempt {attempt + 1} failed for video {video_id}: {error_msg}"
            )

            # Check for specific error types that indicate member-only content
            if any(
                indicator in error_msg.lower()
                for indicator in [
                    "commentsDisabled",
                    "forbidden",
                    "insufficientPermissions",
                    "channelSubscriptionRequired",
                ]
            ):
                logger.info(
                    f"Video {video_id} appears to be member-only or comments disabled - skipping"
                )
                return "member_only"
            elif "quotaExceeded" in error_msg:
                logger.error("YouTube API quota exceeded")
                return False

            if attempt < max_retries - 1:
                logger.info(f"Waiting {delay} seconds before retry...")
                time.sleep(delay)
            else:
                logger.error(f"All {max_retries} attempts failed for video {video_id}")

    return False


def mark_video_as_processed(row_id, success=True, status="ended"):
    """Mark video as processed with success status"""
    try:
        url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_YT_TABLE}?id=eq.{row_id}"
        headers = {
            "apikey": SUPABASE_API_KEY,
            "Authorization": f"Bearer {SUPABASE_API_KEY}",
            "Content-Type": "application/json",
        }

        data = {
            "marked": success,
            "status": status,
        }

        resp = requests.patch(url, headers=headers, json=data, timeout=30)
        resp.raise_for_status()

        logger.info(f"Database updated for video {row_id} with status: {status}")
        return True

    except requests.exceptions.RequestException as e:
        logger.error(f"Request error updating database for video {row_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error updating database for video {row_id}: {e}")
        return False


def remove_custom_emojis(text):
    """Remove custom emoji patterns like :_EmojiName: from text"""
    if not text:
        return text
    try:
        return re.sub(r":_[^:]+:", "", text)
    except Exception as e:
        logger.error(f"Error removing custom emojis: {e}")
        return text


def remove_at_symbol(text):
    """Remove leading @ symbol from usernames (e.g., @Dhruvi -> Dhruvi)"""
    if not text:
        return text
    try:
        return text.lstrip("@")
    except Exception as e:
        logger.error(f"Error removing @ symbol: {e}")
        return text


def truncate_comment(comment_body, max_length=YOUTUBE_COMMENT_MAX_LENGTH):
    """Truncate comment if it exceeds YouTube's character limit"""
    if len(comment_body) <= max_length:
        return comment_body

    # Find a good place to cut (try to avoid cutting in the middle of a timestamp line)
    truncated = comment_body[: max_length - 100]  # Leave some buffer
    last_newline = truncated.rfind("\n")

    if last_newline > 0:
        truncated = truncated[:last_newline]

    truncated += (
        "\n\n[Comment truncated due to length limit]\n\nThank you for using Tsnip."
    )

    logger.warning(
        f"Comment truncated from {len(comment_body)} to {len(truncated)} characters"
    )
    return truncated


def process_single_video(row, video_index, total_videos):
    """Process a single video with comprehensive error handling"""
    try:
        video_id = row["video_id"]
        uuid = row["id"]
        chat_id = row["chat_id"]
        start_time = row["stream_start_time"]

        logger.info(f"[{video_index}/{total_videos}] Processing video {video_id}")

        # Get chat messages
        messages = get_chat_messages(chat_id)
        if not messages:
            logger.warning(f"No messages found for chat {chat_id}")
            return False

        logger.info(f"Found {len(messages)} chat messages")

        # Format timestamps
        lines = []
        for m in messages:
            try:
                timestamp = format_timestamp(
                    start_time, m["user_timestamp"], m["delay"]
                )
                message = m.get("message", "").strip()
                user = m["user_name"]

                # Clean member emojis and @ symbols from user name
                message = remove_custom_emojis(message)
                user = remove_at_symbol(user)

                # Add to comment lines
                if message:
                    lines.append(f"{timestamp} – _{message}_ (by {user})")
                else:
                    lines.append(f"{timestamp} – (by {user})")
            except Exception as e:
                logger.error(f"Error processing message for video {video_id}: {e}")
                continue

        if not lines:
            logger.warning(f"No valid timestamp lines generated for video {video_id}")
            return False

        # Post YouTube comment
        comment_body = (
            "Time stamps:\n\n" + "\n".join(lines) + "\n\nThank you for using Tsnip."
        )

        # Truncate if necessary
        comment_body = truncate_comment(comment_body)

        logger.info(f"Comment length: {len(comment_body)} characters")

        # Post comment with retry logic
        result = post_comment_with_retry(video_id, comment_body)

        if result is True:
            # Successfully posted comment
            if mark_video_as_processed(uuid, success=True, status="ended"):
                logger.info(f"Successfully processed video {video_id}")
                return True
            else:
                logger.error(
                    f"Failed to mark video {video_id} as processed in database"
                )
                return False
        elif result == "member_only":
            # Member-only video, skip comment but mark as processed
            if mark_video_as_processed(uuid, success=True, status="member_only"):
                logger.info(
                    f"Skipped member-only video {video_id} and marked as processed"
                )
                return True
            else:
                logger.error(
                    f"Failed to mark member-only video {video_id} as processed in database"
                )
                return False
        else:
            # Failed to post comment
            logger.error(f"Failed to process video {video_id} - will retry later")
            return False

    except Exception as e:
        logger.error(
            f"Unexpected error processing video {row.get('video_id', 'unknown')}: {e}"
        )
        return False


def handler():
    """Main handler function with comprehensive error handling"""
    try:
        logger.info("Starting YouTube comment processing...")

        # Validate environment variables
        validate_environment()

        # Get unmarked streams
        unmarked_streams = get_unmarked_streams()
        if not unmarked_streams:
            logger.info("No unmarked streams found")
            return

        logger.info(f"Found {len(unmarked_streams)} unmarked streams")

        # Process each video
        processed_count = 0
        failed_count = 0

        for i, row in enumerate(unmarked_streams, 1):
            try:
                # Add small delay between videos to avoid rate limiting
                if i > 1:
                    time.sleep(2)

                success = process_single_video(row, i, len(unmarked_streams))

                if success:
                    processed_count += 1
                else:
                    failed_count += 1

            except Exception as e:
                logger.error(f"Critical error processing video {i}: {e}")
                failed_count += 1
                continue

        logger.info(
            f"Processing complete! Processed: {processed_count}, Failed: {failed_count}"
        )

    except Exception as e:
        logger.error(f"Critical error in main handler: {e}")
        raise


if __name__ == "__main__":
    try:
        handler()
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        exit(1)

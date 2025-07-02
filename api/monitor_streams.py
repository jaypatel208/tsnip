import os
import requests
import time
import re
from dotenv import load_dotenv
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

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


def get_youtube_client():
    creds = Credentials(
        None,
        refresh_token=YOUTUBE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=YOUTUBE_CLIENT_ID,
        client_secret=YOUTUBE_CLIENT_SECRET,
        scopes=["https://www.googleapis.com/auth/youtube.force-ssl"],
    )
    creds.refresh(Request())
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def get_unmarked_streams():
    url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_YT_TABLE}?marked=eq.false&select=video_id,id,chat_id"
    headers = {
        "apikey": SUPABASE_API_KEY,
        "Authorization": f"Bearer {SUPABASE_API_KEY}",
    }
    resp = requests.get(url, headers=headers)
    return resp.json() if resp.status_code == 200 else []


def get_stream_times(video_id):
    url = f"https://www.googleapis.com/youtube/v3/videos?part=liveStreamingDetails&id={video_id}&key={YT_DATA_API_V3}"
    resp = requests.get(url)
    if resp.status_code != 200:
        return None, None
    items = resp.json().get("items", [])
    if not items:
        return None, None

    details = items[0].get("liveStreamingDetails", {})
    return details.get("actualStartTime"), details.get("actualEndTime")


def get_chat_messages(chat_id):
    url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}?chat_id=eq.{chat_id}&select=message,user_name,user_timestamp,delay"
    headers = {
        "apikey": SUPABASE_API_KEY,
        "Authorization": f"Bearer {SUPABASE_API_KEY}",
    }
    resp = requests.get(url, headers=headers)
    return resp.json() if resp.status_code == 200 else []


def format_timestamp(start_time_str, user_time_str, delay):
    start_time = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
    user_time = datetime.fromisoformat(user_time_str)
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


def is_video_ready_for_comments(video_id):
    """Check if video is public and ready for comments, including member-only detection"""
    try:
        url = f"https://www.googleapis.com/youtube/v3/videos?part=status,statistics,snippet&id={video_id}&key={YT_DATA_API_V3}"
        resp = requests.get(url)
        if resp.status_code == 200:
            items = resp.json().get("items", [])
            if items:
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

                print(
                    f"Video {video_id} - Public: {is_public}, Comments disabled: {comments_disabled}, Member-only: {is_member_only}"
                )

                return {
                    "can_comment": is_public
                    and not comments_disabled
                    and not is_member_only,
                    "is_member_only": is_member_only,
                    "is_public": is_public,
                    "comments_disabled": comments_disabled,
                }
    except Exception as e:
        print(f"Error checking video status for {video_id}: {e}")

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
            print(
                f"Attempting to post comment to video {video_id} (attempt {attempt + 1}/{max_retries})"
            )

            # Check if video is ready for comments
            video_status = is_video_ready_for_comments(video_id)

            if video_status["is_member_only"]:
                print(
                    f"Video {video_id} is member-only - skipping comment but marking as processed"
                )
                return "member_only"

            if not video_status["can_comment"]:
                print(f"Video {video_id} not ready for comments yet")
                if attempt < max_retries - 1:
                    print(f"Waiting {delay} seconds before retry...")
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

            print(f"✓ Comment posted successfully to video {video_id}")
            return True

        except Exception as e:
            error_msg = str(e)
            print(f"✗ Attempt {attempt + 1} failed for video {video_id}: {error_msg}")

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
                print(
                    f"Video {video_id} appears to be member-only or comments disabled - skipping"
                )
                return "member_only"
            elif "quotaExceeded" in error_msg:
                print("YouTube API quota exceeded")
                return False

            if attempt < max_retries - 1:
                print(f"Waiting {delay} seconds before retry...")
                time.sleep(delay)
            else:
                print(f"✗ All {max_retries} attempts failed for video {video_id}")

    return False


def mark_video_as_processed(row_id, stream_start_time, success=True, status="ended"):
    """Mark video as processed with success status"""
    if isinstance(stream_start_time, str):
        stream_start_time = datetime.fromisoformat(
            stream_start_time.replace("Z", "+00:00")
        )
    stream_start_time_str = stream_start_time.isoformat()

    url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_YT_TABLE}?id=eq.{row_id}"
    headers = {
        "apikey": SUPABASE_API_KEY,
        "Authorization": f"Bearer {SUPABASE_API_KEY}",
        "Content-Type": "application/json",
    }

    data = {
        "marked": success,
        "status": status,
        "stream_start_time": stream_start_time_str,
    }

    try:
        resp = requests.patch(url, headers=headers, json=data)
        if resp.status_code == 200:
            print(f"✓ Database updated for video {row_id} with status: {status}")
        else:
            print(f"✗ Failed to update database for video {row_id}: {resp.text}")
    except Exception as e:
        print(f"✗ Error updating database for video {row_id}: {e}")


def remove_custom_emojis(text):
    """Remove custom emoji patterns like :_EmojiName: from text"""
    if not text:
        return text
    return re.sub(r":_[^:]+:", "", text)


def remove_at_symbol(text):
    """Remove leading @ symbol from usernames (e.g., @Dhruvi -> Dhruvi)"""
    if not text:
        return text
    return text.lstrip("@")


def handler():
    """Main handler function"""
    print("Starting YouTube comment processing...")

    unmarked_streams = get_unmarked_streams()
    print(f"Found {len(unmarked_streams)} unmarked streams")

    for i, row in enumerate(unmarked_streams, 1):
        video_id = row["video_id"]
        uuid = row["id"]
        chat_id = row["chat_id"]

        print(f"\n[{i}/{len(unmarked_streams)}] Processing video {video_id}")

        # Get stream times
        start_time, end_time = get_stream_times(video_id)
        if not start_time or not end_time:
            print(f"✗ No stream times found for video {video_id}")
            continue

        print(f"Stream times: {start_time} to {end_time}")

        # Get chat messages
        messages = get_chat_messages(chat_id)
        if not messages:
            print(f"✗ No messages found for chat {chat_id}")
            continue

        print(f"Found {len(messages)} chat messages")

        # Format timestamps
        lines = []
        for m in messages:
            timestamp = format_timestamp(start_time, m["user_timestamp"], m["delay"])
            message = m.get("message", "").strip()
            user = m["user_name"]

            # Clean member emojis and @ symbols from user name
            message = remove_custom_emojis(message)
            user = remove_at_symbol(user)

            if message:
                lines.append(f"{timestamp} – _{message}_ (by {user})")
            else:
                lines.append(f"{timestamp} – (by {user})")

        comment_body = (
            "Time stamps:\n\n" + "\n".join(lines) + "\n\nThank you for using Tsnip."
        )

        print(f"Comment length: {len(comment_body)} characters")

        # Post comment with retry logic
        result = post_comment_with_retry(video_id, comment_body)

        if result == True:
            # Successfully posted comment
            mark_video_as_processed(uuid, start_time, success=True, status="ended")
            print(f"✓ Successfully processed video {video_id}")
        elif result == "member_only":
            # Member-only video, skip comment but mark as processed
            mark_video_as_processed(
                uuid, start_time, success=True, status="member_only"
            )
            print(f"✓ Skipped member-only video {video_id} and marked as processed")
        else:
            # Failed to post comment
            print(f"✗ Failed to process video {video_id} - will retry later")
            # Don't mark as processed, so it will be retried next time -

    print("\nProcessing complete!")


if __name__ == "__main__":
    handler()

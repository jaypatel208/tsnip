import os
import requests
from dotenv import load_dotenv
from datetime import datetime
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

# Load environment variables -
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
    return build("youtube", "v3", credentials=creds)


def get_unmarked_streams():
    url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_YT_TABLE}?marked=eq.false&select=video_id,id,chat_id,title"
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
    url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}?chat_id=eq.{chat_id}&select=message,user_name,user_timestamp"
    headers = {
        "apikey": SUPABASE_API_KEY,
        "Authorization": f"Bearer {SUPABASE_API_KEY}",
    }
    resp = requests.get(url, headers=headers)
    return resp.json() if resp.status_code == 200 else []


def format_timestamp(start_time_str, user_time_str):
    start_time = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
    user_time = datetime.fromisoformat(user_time_str)
    delta = user_time - start_time
    total_seconds = max(0, int(delta.total_seconds()))  # avoid negatives
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return (
        f"{hours:02}:{minutes:02}:{seconds:02}"
        if hours
        else f"{minutes:02}:{seconds:02}"
    )


def post_comment(video_id, comment_body):
    try:
        yt = get_youtube_client()
        yt.commentThreads().insert(
            part="snippet",
            body={
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {"snippet": {"textOriginal": comment_body}},
                }
            },
        ).execute()
        return True
    except:
        return False


def mark_video_as_processed(row_id):
    url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_YT_TABLE}?id=eq.{row_id}"
    headers = {
        "apikey": SUPABASE_API_KEY,
        "Authorization": f"Bearer {SUPABASE_API_KEY}",
        "Content-Type": "application/json",
    }
    data = {"marked": True, "status": "ended"}
    requests.patch(url, headers=headers, json=data)


def handler():
    for row in get_unmarked_streams():
        video_id = row["video_id"]
        uuid = row["id"]
        chat_id = row["chat_id"]
        title = row["title"]

        start_time, end_time = get_stream_times(video_id)
        if not start_time or not end_time:
            continue

        messages = get_chat_messages(chat_id)
        if not messages:
            continue

        lines = []
        for m in messages:
            timestamp = format_timestamp(start_time, m["user_timestamp"])
            message = m.get("message", "").strip()
            user = m["user_name"]

            if title and message:
                lines.append(f"{timestamp} | {message} | {user}")
            else:
                lines.append(f"{timestamp} | {user}")

        comment_body = (
            (f"Time stamps of {title}:\n\n" if title else "Time stamps:\n\n")
            + "\n".join(lines)
            + "\n\nThank you for using Tsnip."
        )

        if post_comment(video_id, comment_body):
            mark_video_as_processed(uuid)


if __name__ == "__main__":
    handler()

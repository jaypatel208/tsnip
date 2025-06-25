# app.py
from flask import Flask, request, Response
import requests
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone

# YouTube processor will be imported conditionally when needed

# Load environment variables
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_API_KEY = os.getenv("SUPABASE_API_KEY")
SUPABASE_TABLE = os.getenv("SUPABASE_TABLE")
SUPABASE_YT_TABLE = os.getenv("SUPABASE_YT_TABLE")
TOOL_USED = os.getenv("TOOL_USED")

app = Flask(__name__)

# YouTube processor will be initialized conditionally
youtube_processor = None


def check_chat_id_exists(chat_id):
    """Check if chat_id already exists in SUPABASE_YT_TABLE"""
    if not SUPABASE_YT_TABLE:
        print("SUPABASE_YT_TABLE not configured")
        return False

    headers = {
        "apikey": SUPABASE_API_KEY,
        "Authorization": f"Bearer {SUPABASE_API_KEY}",
    }

    try:
        response = requests.get(
            f"{SUPABASE_URL}/rest/v1/{SUPABASE_YT_TABLE}?chat_id=eq.{chat_id}&select=chat_id&limit=1",
            headers=headers,
            timeout=10,
        )

        if response.status_code == 200:
            existing = response.json()
            return len(existing) > 0
        else:
            print(f"Error checking chat_id existence: {response.text}")
            return False
    except Exception as e:
        print(f"Error checking chat_id: {str(e)}")
        return False


def ensure_youtube_processor_initialized():
    """Initialize YouTube processor if not already done"""
    global youtube_processor
    if youtube_processor is None:
        try:
            # Import YouTube processor functions only when needed
            from youtube_processor import initialize_youtube_processor

            print("Initializing YouTube processor...")
            youtube_processor = initialize_youtube_processor()
        except ImportError as e:
            print(f"Warning: Could not import youtube_processor: {e}")
            return None
    return youtube_processor


def insert_to_supabase(channelid, chat_id, delay, message, user, user_timestamp):
    """Insert clip data to main Supabase table"""
    data = {
        "channel_id": channelid,
        "chat_id": chat_id,
        "user_timestamp": user_timestamp,
        "delay": int(delay),
        "message": message,
        "user_name": user,
    }

    headers = {
        "apikey": SUPABASE_API_KEY,
        "Authorization": f"Bearer {SUPABASE_API_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

    response = requests.post(
        f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}", headers=headers, json=data
    )

    if response.status_code != 201:
        print("Supabase insert failed:", response.text)
        return False
    return True


@app.route("/api/clip", methods=["GET", "POST"])
def clip_handler():
    """Phase 1: Handle clip requests and store them"""
    user = request.args.get("user") or request.form.get("user") or "unknown"
    channel_id = (
        request.args.get("channelid") or request.form.get("channelid") or "id22"
    )
    chat_id = request.args.get("chatId") or request.form.get("chatId") or "idchat22"
    msg = request.args.get("msg") or request.form.get("msg") or ""
    delay = int(request.args.get("delay") or request.form.get("delay") or "22")

    # Compute actual user timestamp by subtracting delay
    server_time = datetime.now(timezone.utc)
    user_time = server_time - timedelta(seconds=delay)
    user_timestamp = user_time.isoformat()

    # Phase 1: Insert clip data to main table
    success = insert_to_supabase(channel_id, chat_id, delay, msg, user, user_timestamp)

    # Phase 2: Queue YouTube processing (runs in background after delay)
    if success and channel_id != "id22":  # Only process real channel IDs
        # Check if chat_id already exists in SUPABASE_YT_TABLE
        if not check_chat_id_exists(chat_id):
            print(
                f"Chat ID {chat_id} not found in YT table, initializing YouTube processor..."
            )
            processor = ensure_youtube_processor_initialized()
            if processor:
                try:
                    # Import queue function when needed
                    from youtube_processor import queue_youtube_processing

                    print(
                        f"Queuing YouTube processing for channel: {channel_id}, chat: {chat_id}"
                    )
                    queue_youtube_processing(
                        chat_id, channel_id, delay=5
                    )  # 5 second delay
                except ImportError as e:
                    print(f"Warning: Could not import queue_youtube_processing: {e}")
            else:
                print("YouTube processor could not be initialized")
        else:
            print(
                f"Chat ID {chat_id} already exists in YT table, skipping YouTube processing"
            )

    # Return immediate response (don't wait for YouTube processing)
    title_part = f" — titled '{msg}'" if msg else ""
    comment = (
        f"Timestamped (with a {delay}s delay) by {user}{title_part}. "
        f"All timestamps get commented after the stream ends. Tool used: {TOOL_USED}"
    )

    return Response(comment, mimetype="text/plain")


@app.route("/api/health", methods=["GET"])
def health_check():
    """Health check endpoint"""
    processor_status = "initialized" if youtube_processor else "not initialized"
    return {"status": "healthy", "youtube_processor": processor_status}


@app.route("/api/youtube/manual-process", methods=["POST"])
def manual_youtube_process():
    """Manual trigger for YouTube processing (for testing)"""
    data = request.get_json() or {}
    chat_id = data.get("chat_id") or request.args.get("chatId")
    channel_id = data.get("channel_id") or request.args.get("channelId")

    if not chat_id or not channel_id:
        return {"error": "Missing chat_id or channel_id"}, 400

    # Ensure processor is initialized for manual processing
    processor = ensure_youtube_processor_initialized()
    if not processor:
        return {"error": "YouTube processor could not be initialized"}, 500

    try:
        # Import queue function when needed
        from youtube_processor import queue_youtube_processing

        print(
            f"Manual YouTube processing triggered for channel: {channel_id}, chat: {chat_id}"
        )
        queue_youtube_processing(chat_id, channel_id, delay=1)  # Immediate processing

        return {
            "message": "YouTube processing queued",
            "chat_id": chat_id,
            "channel_id": channel_id,
        }
    except ImportError as e:
        return {"error": f"Could not import YouTube processor: {str(e)}"}, 500


if __name__ == "__main__":
    print("Starting Flask app with conditional YouTube processor initialization...")
    app.run(debug=True)

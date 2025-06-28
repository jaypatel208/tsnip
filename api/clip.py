from flask import Flask, request, Response, jsonify
import requests
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
from api.monitor_streams import handler as monitor_handler


# Load environment variables
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_API_KEY = os.getenv("SUPABASE_API_KEY")
SUPABASE_TABLE = os.getenv("SUPABASE_TABLE")
SUPABASE_YT_TABLE = os.getenv("SUPABASE_YT_TABLE")
TOOL_USED = os.getenv("TOOL_USED")
CRON_SECRET = os.getenv("CRON_SECRET")

app = Flask(__name__)

# YouTube processor will be initialized conditionally
youtube_processor = None
youtube_processor_available = False

try:
    from . import youtube_processor

    youtube_processor_available = True
    print("YouTube processor module is available")
except ImportError as e:
    print(f"YouTube processor module not available: {e}")
    youtube_processor_available = False


def is_placeholder_value(value):
    """Check if a value is a placeholder/template variable"""
    return str(value) in ["$(user)", "$(chatid)", "$(channelid)", "$(querystring)"]


def check_chat_id_exists(chat_id):
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
    global youtube_processor

    if not youtube_processor_available:
        print("YouTube processor module not available, skipping initialization")
        return None

    if youtube_processor is None:
        try:
            print("Initializing YouTube processor...")
            youtube_processor = youtube_processor.initialize_youtube_processor()
            print("YouTube processor initialized successfully")
        except Exception as e:
            print(f"Error initializing YouTube processor: {e}")
            return None
    return youtube_processor


def insert_to_supabase(channelid, chat_id, delay, message, user, user_timestamp):
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
    user = request.args.get("user") or request.form.get("user") or "unknown"
    channel_id = (
        request.args.get("channelid") or request.form.get("channelid") or "id22"
    )
    chat_id = request.args.get("chatId") or request.form.get("chatId") or "idchat22"
    msg = request.args.get("msg") or request.form.get("msg") or ""
    delay = int(request.args.get("delay") or request.form.get("delay") or "22")

    # Check if any parameter is a placeholder - if so, don't save to DB
    if (
        is_placeholder_value(user)
        or is_placeholder_value(channel_id)
        or is_placeholder_value(chat_id)
        or (msg and is_placeholder_value(msg))
    ):

        error_response = "Error: Command not executed properly. Make sure to use this command in a stream chat where the bot variables can be resolved."
        print(
            f"Placeholder values detected - user: {user}, channel_id: {channel_id}, chat_id: {chat_id}, msg: {msg}"
        )
        return Response(error_response, mimetype="text/plain", status=400)

    server_time = datetime.now(timezone.utc)
    user_time = server_time - timedelta(seconds=delay)
    user_timestamp = user_time.isoformat()

    success = insert_to_supabase(channel_id, chat_id, delay, msg, user, user_timestamp)

    if not success:
        error_response = "Error: Failed to save timestamp. Please try again."
        return Response(error_response, mimetype="text/plain", status=500)

    if success:
        if not check_chat_id_exists(chat_id):
            print(
                f"Chat ID {chat_id} not found in YT table, attempting YouTube processing..."
            )

            processor = ensure_youtube_processor_initialized()
            if processor:
                print(
                    f"Processing YouTube request immediately for channel: {channel_id}, chat: {chat_id}"
                )
                try:
                    yt_success = processor.process_youtube_request(chat_id, channel_id)
                    if yt_success:
                        print("YouTube processing completed successfully")
                    else:
                        print("YouTube processing failed during execution")
                except Exception as e:
                    print(f"Error during YouTube processing: {str(e)}")
            else:
                print("YouTube processor could not be initialized")
        else:
            print(f"Chat ID {chat_id} already exists in YT table, skipping processing")

    title_part = f" — titled '{msg}'" if msg else ""
    comment = (
        f"Timestamped (with a -{delay}s delay) by {user}{title_part}. "
        f"All timestamps get commented after the stream ends. Tool used: {TOOL_USED}"
    )

    return Response(comment, mimetype="text/plain")


@app.route("/api/health", methods=["GET"])
def health_check():
    processor_status = "initialized" if youtube_processor else "not initialized"
    module_status = "available" if youtube_processor_available else "not available"

    return {
        "status": "healthy",
        "youtube_processor": processor_status,
        "youtube_module": module_status,
    }


@app.route("/api/youtube/manual-process", methods=["POST"])
def manual_youtube_process():
    if not youtube_processor_available:
        return {"error": "YouTube processor module not available"}, 503

    data = request.get_json() or {}
    chat_id = data.get("chat_id") or request.args.get("chatId")
    channel_id = data.get("channel_id") or request.args.get("channelId")

    if not chat_id or not channel_id:
        return {"error": "Missing chat_id or channel_id"}, 400

    processor = ensure_youtube_processor_initialized()
    if not processor:
        return {"error": "YouTube processor could not be initialized"}, 500

    try:
        print(
            f"Manual YouTube processing triggered for channel: {channel_id}, chat: {chat_id}"
        )
        success = processor.process_youtube_request(chat_id, channel_id)
        if success:
            return {
                "message": "YouTube processing completed",
                "chat_id": chat_id,
                "channel_id": channel_id,
            }
        else:
            return {"error": "YouTube processing failed"}, 500
    except Exception as e:
        print(f"Exception in manual processing: {str(e)}")
        return {"error": str(e)}, 500


@app.route("/api/monitor-streams", methods=["GET", "POST"])
def cron_monitor_streams():
    secret = request.args.get("secret") or request.headers.get("X-Cron-Secret")
    if not secret or secret != CRON_SECRET:
        return jsonify({"error": "Unauthorized"}), 401

    try:
        monitor_handler()
        return jsonify({"message": "Stream monitoring executed successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("Starting Flask app with conditional YouTube processor initialization...")
    print(f"YouTube processor available: {youtube_processor_available}")
    app.run(debug=True)

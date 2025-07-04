from flask import Flask, request, Response, jsonify
import requests
import os
from dotenv import load_dotenv
from datetime import datetime, timezone
from api.monitor_streams import handler as monitor_handler
import logging

# Load environment variables
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_API_KEY = os.getenv("SUPABASE_API_KEY")
SUPABASE_TABLE = os.getenv("SUPABASE_TABLE")
SUPABASE_YT_TABLE = os.getenv("SUPABASE_YT_TABLE")
SUPABASE_YT_CHANNEL_TABLE = os.getenv("SUPABASE_YT_CHANNEL_TABLE")
TOOL_USED = os.getenv("TOOL_USED")
CRON_SECRET = os.getenv("CRON_SECRET")
CRON_SECRET_DC_KEEP_ALIVE = os.getenv("CRON_SECRET_DC_KEEP_ALIVE")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

DEFAULT_TEMPLATE = (
    "Timestamped (with a -{delay}s delay) by {user}{title_part}."
    "All timestamps get commented after the stream ends. Tool used: {tool_used}"
)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

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


def get_comment_template(channel_id):
    headers = {
        "apikey": SUPABASE_API_KEY,
        "Authorization": f"Bearer {SUPABASE_API_KEY}",
    }

    try:
        response = requests.get(
            f"{SUPABASE_URL}/rest/v1/{SUPABASE_YT_CHANNEL_TABLE}?channel_id=eq.{channel_id}&select=channel_template",
            headers=headers,
            timeout=10,
        )

        if response.status_code == 200:
            data = response.json()
            if data and data[0]["channel_template"]:
                return data[0]["channel_template"], True
    except Exception as e:
        print(f"Error fetching template from Supabase: {e}")

    return DEFAULT_TEMPLATE, False


@app.route("/api/clip", methods=["GET", "POST"])
def clip_handler():
    user = request.args.get("user") or request.form.get("user")
    channel_id = request.args.get("channelid") or request.form.get("channelid")
    chat_id = request.args.get("chatId") or request.form.get("chatId")
    msg = request.args.get("msg") or request.form.get("msg") or ""
    delay = int(request.args.get("delay") or request.form.get("delay"))

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

    user_timestamp = datetime.now(timezone.utc).isoformat()

    success = insert_to_supabase(channel_id, chat_id, delay, msg, user, user_timestamp)

    if not success:
        return Response(
            "Error: Failed to save timestamp. Please try again.",
            mimetype="text/plain",
            status=500,
        )

    if not check_chat_id_exists(chat_id):
        print(
            f"Chat ID {chat_id} not found in YT table, attempting YouTube processing..."
        )
        processor = ensure_youtube_processor_initialized()
        if processor:
            try:
                yt_success = processor.process_youtube_request(chat_id, channel_id)
                if yt_success:
                    print("YouTube processing completed successfully")
                else:
                    print("YouTube processing failed")
            except Exception as e:
                print(f"Error during YouTube processing: {str(e)}")
    else:
        print(f"Chat ID {chat_id} already exists, skipping YouTube processing")

    title_part = f" — titled '{msg}'" if msg else ""
    template, is_custom = get_comment_template(channel_id)

    comment = template.format(
        user=user, delay=delay, title_part=title_part, tool_used=TOOL_USED
    )

    print(
        f"Using template for channel {channel_id}: {'custom' if is_custom else 'default'}"
    )

    return Response(comment, mimetype="text/plain")


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


@app.route("/api/dc-keepalive", methods=["GET", "POST"])
def discord_keepalive():
    # Log the incoming request
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    logger.info(f"Keepalive request from {client_ip}")

    if not CRON_SECRET_DC_KEEP_ALIVE:
        logger.error("Cron secret not configured")
        return (
            jsonify({"status": "error", "message": "Cron secret not configured"}),
            500,
        )

    provided_secret = request.args.get("secret") or request.headers.get("X-Cron-Secret")

    if provided_secret != CRON_SECRET_DC_KEEP_ALIVE:
        logger.warning(f"Invalid secret attempt from {client_ip}")
        return jsonify({"status": "error", "message": "Invalid or missing secret"}), 401

    try:
        start_time = datetime.now()

        response = requests.get(
            "https://discord.com/api/v10/users/@me",
            headers={
                "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )

        end_time = datetime.now()
        response_time = (end_time - start_time).total_seconds()

        if response.status_code == 200:
            bot_data = response.json()
            logger.info(f"Keepalive successful for bot: {bot_data.get('username')}")

            return jsonify(
                {
                    "status": "success",
                    "message": "Discord bot keepalive successful",
                    "bot_username": bot_data.get("username"),
                    "bot_discriminator": bot_data.get("discriminator"),
                    "response_time_ms": round(response_time * 1000, 2),
                    "timestamp": datetime.now().isoformat(),
                }
            )
        else:
            logger.warning(f"Discord API returned {response.status_code}")
            return jsonify(
                {
                    "status": "warning",
                    "message": f"Discord API returned {response.status_code}",
                    "response_code": response.status_code,
                    "timestamp": datetime.now().isoformat(),
                }
            )

    except Exception as e:
        logger.error(f"Keepalive error: {e}")
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Keepalive failed",
                    "error": str(e),
                    "timestamp": datetime.now().isoformat(),
                }
            ),
            500,
        )


if __name__ == "__main__":
    print("Starting Flask app with conditional YouTube processor initialization...")
    print(f"YouTube processor available: {youtube_processor_available}")
    app.run(debug=True)

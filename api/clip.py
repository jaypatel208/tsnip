from flask import Flask, request, Response, jsonify
import requests
import os
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
from api.monitor_streams import handler as monitor_handler
import logging

# Load environment variables
load_dotenv()

# Set up logging - only use StreamHandler for serverless environments
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

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


def validate_environment():
    """Validate that all required environment variables are set"""
    required_vars = [
        "SUPABASE_URL",
        "SUPABASE_API_KEY",
        "SUPABASE_TABLE",
        "SUPABASE_YT_TABLE",
        "SUPABASE_YT_CHANNEL_TABLE",
        "TOOL_USED",
        "CRON_SECRET",
        "CRON_SECRET_DC_KEEP_ALIVE",
        "DISCORD_BOT_TOKEN",
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


app = Flask(__name__)

youtube_processor = None
youtube_processor_available = False

try:
    from . import youtube_processor

    youtube_processor_available = True
    logger.info("YouTube processor module is available")
except ImportError as e:
    logger.warning(f"YouTube processor module not available: {e}")
    youtube_processor_available = False


def is_placeholder_value(value):
    return str(value) in ["$(user)", "$(chatid)", "$(channelid)", "$(querystring)"]


def check_chat_id_exists(chat_id):
    if not SUPABASE_YT_TABLE:
        logger.error("SUPABASE_YT_TABLE not configured")
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
            logger.error(f"Error checking chat_id existence: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Error checking chat_id: {str(e)}")
        return False


def get_discord_channel_id(channel_id):
    """Get Discord channel ID for a YouTube channel"""
    if not SUPABASE_YT_CHANNEL_TABLE:
        logger.error("SUPABASE_YT_CHANNEL_TABLE not configured")
        return None

    url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_YT_CHANNEL_TABLE}?channel_id=eq.{channel_id}&select=dc_channel_id"
    headers = {
        "apikey": SUPABASE_API_KEY,
        "Authorization": f"Bearer {SUPABASE_API_KEY}",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data and data[0].get("dc_channel_id"):
                return data[0]["dc_channel_id"]
    except Exception as e:
        logger.error(f"Error fetching Discord channel ID: {e}")

    return None


def format_timestamp(start_time_str, user_time_str, delay):
    """Format timestamp for display"""
    try:
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
    except Exception as e:
        logger.error(f"Error formatting timestamp: {e}")
        return "00:00"


def timestamp_to_seconds(timestamp):
    """Convert timestamp (HH:MM:SS or MM:SS) to seconds"""
    try:
        parts = timestamp.split(":")
        if len(parts) == 2:  # MM:SS
            minutes, seconds = map(int, parts)
            return minutes * 60 + seconds
        elif len(parts) == 3:  # HH:MM:SS
            hours, minutes, seconds = map(int, parts)
            return hours * 3600 + minutes * 60 + seconds
        return 0
    except Exception as e:
        logger.error(f"Error converting timestamp to seconds: {e}")
        return 0


def get_live_stream_info(channel_id):
    """Get current live stream info for a channel"""
    if not SUPABASE_YT_TABLE:
        return None, None, None

    headers = {
        "apikey": SUPABASE_API_KEY,
        "Authorization": f"Bearer {SUPABASE_API_KEY}",
    }

    try:
        # Get the most recent live stream for this channel that's not ended
        response = requests.get(
            f"{SUPABASE_URL}/rest/v1/{SUPABASE_YT_TABLE}?channel_id=eq.{channel_id}&status=neq.ended&order=created_at.desc&limit=1",
            headers=headers,
            timeout=10,
        )

        if response.status_code == 200:
            data = response.json()
            if data:
                return (
                    data[0].get("video_id"),
                    data[0].get("video_title", "Live Stream"),
                    data[0].get("start_time"),
                )
    except Exception as e:
        logger.error(f"Error fetching live stream info: {e}")

    return None, None, None


def send_discord_message_immediate(
    discord_channel_id, video_id, video_title, message, username, timestamp=None
):
    """Send immediate clip notification to Discord channel with timestamp"""
    if not DISCORD_BOT_TOKEN:
        logger.error("Discord bot token not configured")
        return False

    # If we don't have video_id, log and return
    if not video_id:
        logger.warning(
            f"No video id found for Discord notification to channel {discord_channel_id}"
        )
        return False

    # If we don't have timestamp, log and return
    if not timestamp:
        logger.warning(
            f"No timestamp found for Discord notification to channel {discord_channel_id}"
        )
        return False

    # Create YouTube URL with timestamp
    youtube_url = f"https://www.youtube.com/watch?v={video_id}"
    seconds = timestamp_to_seconds(timestamp)
    youtube_url += f"&t={seconds}s"

    # YouTube thumbnail URL
    thumbnail_url = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"

    embed_title = message.strip() if message.strip() else f"📎 New Clip Created"

    embed_fields = [
        {"name": "🎬 Stream", "value": video_title, "inline": False},
        {
            "name": "📝 Message",
            "value": message if message else "No message",
            "inline": False,
        },
        {"name": "👤 Created by", "value": username, "inline": True},
    ]

    # Add timestamp field
    embed_fields.append({"name": "⏰ Timestamp", "value": timestamp, "inline": True})

    embed = {
        "title": embed_title,
        "url": youtube_url,
        "color": 0xFF0000,  # Red color like YouTube
        "thumbnail": {"url": thumbnail_url},
        "fields": embed_fields,
        "footer": {"text": "Tsnip • Click title to watch at this moment"},
    }

    payload = {"embeds": [embed]}

    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            f"https://discord.com/api/v10/channels/{discord_channel_id}/messages",
            json=payload,
            headers=headers,
            timeout=10,
        )

        if response.status_code == 200:
            logger.info("✓ Sent immediate Discord notification with timestamp")
            return True
        else:
            logger.error(
                f"✗ Failed to send Discord notification: {response.status_code} - {response.text}"
            )
            return False

    except Exception as e:
        logger.error(f"✗ Error sending Discord notification: {e}")
        return False


def ensure_youtube_processor_initialized():
    global youtube_processor

    if not youtube_processor_available:
        logger.warning(
            "YouTube processor module not available, skipping initialization"
        )
        return None

    if youtube_processor is None:
        try:
            logger.info("Initializing YouTube processor...")
            youtube_processor = youtube_processor.initialize_youtube_processor()
            logger.info("YouTube processor initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing YouTube processor: {e}")
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

    try:
        response = requests.post(
            f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}", headers=headers, json=data
        )

        if response.status_code != 201:
            logger.error(f"Supabase insert failed: {response.text}")
            return False

        return True

    except Exception as e:
        logger.error(f"Error in insert_to_supabase: {e}")
        return False


def send_discord_notification(channelid, message, user, user_timestamp, delay):
    discord_channel_id = get_discord_channel_id(channelid)
    if not discord_channel_id:
        logger.warning(
            f"⚠ No Discord integration found for YouTube channel {channelid}"
        )
        return False

    logger.info(f"✓ Discord channel found for YouTube channel {channelid}")

    video_id, video_title, stream_start_time = get_live_stream_info(channelid)

    timestamp = None
    if video_id and stream_start_time:
        timestamp = format_timestamp(stream_start_time, user_timestamp, delay)
        logger.info(f"✓ Calculated timestamp: {timestamp}")
    elif video_id:
        logger.warning(
            f"⚠ Stream found but no start time available in DB for video {video_id}"
        )
    else:
        logger.warning(f"⚠ No active stream found for channel {channelid}")

    clean_user = user.lstrip("@") if user else "Unknown"

    success = send_discord_message_immediate(
        discord_channel_id,
        video_id,
        video_title,
        message,
        clean_user,
        timestamp,
    )

    if success:
        logger.info("✓ Immediate Discord notification sent successfully")
    else:
        logger.error("✗ Failed to send immediate Discord notification")

    return success


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
        logger.error(f"Error fetching template from Supabase: {e}")

    return DEFAULT_TEMPLATE, False


@app.route("/api/clip", methods=["GET", "POST"])
def clip_handler():
    # Validate environment variables
    validate_environment()

    user = request.args.get("user") or request.form.get("user")
    channel_id = request.args.get("channelid") or request.form.get("channelid")
    chat_id = request.args.get("chatId") or request.form.get("chatId")
    msg = request.args.get("msg") or request.form.get("msg") or ""
    delay = request.args.get("delay") or request.form.get("delay")

    # Input validation
    if not all([user, channel_id, chat_id, delay is not None]):
        logger.error("Missing required parameters in clip request")
        return Response(
            "Missing required parameters", mimetype="text/plain", status=400
        )

    try:
        delay = int(delay)
    except (ValueError, TypeError):
        logger.error(f"Invalid delay parameter: {delay}")
        return Response("Invalid delay parameter", mimetype="text/plain", status=400)

    if (
        is_placeholder_value(user)
        or is_placeholder_value(channel_id)
        or is_placeholder_value(chat_id)
        or (msg and is_placeholder_value(msg))
    ):
        error_response = "Error: Command not executed properly. Make sure to use this command in a stream chat where the bot variables can be resolved."
        logger.error(
            f"Placeholder values detected - user: {user}, channel_id: {channel_id}, chat_id: {chat_id}, msg: {msg}"
        )
        return Response(error_response, mimetype="text/plain", status=400)

    logger.info(f"Processing clip for channel {channel_id}, user {user}")

    user_timestamp = datetime.now(timezone.utc).isoformat()

    # Insert to Supabase
    success = insert_to_supabase(channel_id, chat_id, delay, msg, user, user_timestamp)

    if not success:
        logger.error("Failed to save timestamp to database")
        return Response(
            "Error: Failed to save timestamp. Please try again.",
            mimetype="text/plain",
            status=500,
        )

    # Check if we need to process YouTube data
    if not check_chat_id_exists(chat_id):
        logger.info(
            f"Chat ID {chat_id} not found in YT table, attempting YouTube processing..."
        )
        processor = ensure_youtube_processor_initialized()
        if processor:
            try:
                yt_success = processor.process_youtube_request(chat_id, channel_id)
                if yt_success:
                    logger.info("YouTube processing completed successfully")
                else:
                    logger.warning("YouTube processing failed")
            except Exception as e:
                logger.error(f"Error during YouTube processing: {str(e)}")
    else:
        logger.info(f"Chat ID {chat_id} already exists, skipping YouTube processing")

    # Send discord notificaion
    send_discord_notification(channel_id, msg, user, user_timestamp, delay)

    title_part = f" — titled '{msg}'" if msg else ""
    template, is_custom = get_comment_template(channel_id)

    comment = template.format(
        user=user, delay=delay, title_part=title_part, tool_used=TOOL_USED
    )

    logger.info(
        f"Using template for channel {channel_id}: {'custom' if is_custom else 'default'}"
    )

    return Response(comment, mimetype="text/plain")


@app.route("/api/monitor-streams", methods=["GET", "POST"])
def cron_monitor_streams():
    secret = request.args.get("secret") or request.headers.get("X-Cron-Secret")
    if not secret or secret != CRON_SECRET:
        logger.warning("Unauthorized access attempt to monitor-streams endpoint")
        return jsonify({"error": "Unauthorized"}), 401

    try:
        logger.info("Executing stream monitoring...")
        monitor_handler()
        logger.info("Stream monitoring executed successfully")
        return jsonify({"message": "Stream monitoring executed successfully"}), 200
    except Exception as e:
        logger.error(f"Error in stream monitoring: {str(e)}")
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


@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})


if __name__ == "__main__":
    logger.info(
        "Starting Flask app with conditional YouTube processor initialization..."
    )
    logger.info(f"YouTube processor available: {youtube_processor_available}")
    app.run(debug=True)

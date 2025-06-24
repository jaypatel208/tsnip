from flask import Flask, request, jsonify
import requests
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone

# Load environment variable
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_API_KEY = os.getenv("SUPABASE_API_KEY")
SUPABASE_TABLE = os.getenv("SUPABASE_TABLE")

app = Flask(__name__)


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


@app.route("/api/clip", methods=["GET", "POST"])
def clip_handler():
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

    insert_to_supabase(channel_id, chat_id, delay, msg, user, user_timestamp)

    return jsonify(
        {
            "message": f"User timestamp marked at {user_timestamp} (delay {delay}s) by {user} with chat id {chat_id} and channel id {channel_id}",
            "msg": msg,
        }
    )


if __name__ == "__main__":
    app.run(debug=True)

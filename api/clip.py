from flask import Flask, request, jsonify
import requests
import os
from dotenv import load_dotenv
from datetime import datetime, timezone

# Load environment variables
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_API_KEY = os.getenv("SUPABASE_API_KEY")
SUPABASE_TABLE = os.getenv("SUPABASE_TABLE")

app = Flask(__name__)

def insert_to_supabase(chat_id, delay, message, user, event_timestamp):
    data = {
        "chat_id": chat_id,
        "event_timestamp": event_timestamp,
        "delay": int(delay),
        "message": message,
        "user_name": user
    }

    headers = {
        "apikey": SUPABASE_API_KEY,
        "Authorization": f"Bearer {SUPABASE_API_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }

    response = requests.post(
        f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}",
        headers=headers,
        json=data
    )

    if response.status_code != 201:
        print("Supabase insert failed:", response.text)

@app.route('/api/clip', methods=['GET', 'POST'])
def clip_handler():
    # Support GET query params or POST body
    user = request.args.get('user') or request.form.get('user') or 'unknown'
    chat_id = request.args.get('chatId') or request.form.get('chatId') or 'id22'
    msg = request.args.get('msg') or request.form.get('msg') or ''
    delay = request.args.get('delay') or request.form.get('delay') or '22'

    event_timestamp = datetime.now(timezone.utc).isoformat()

    insert_to_supabase(chat_id, delay, msg, user, event_timestamp)

    return jsonify({
        "message": f"Timestamp marked at {event_timestamp} (delay {delay}s) by {user} with chat id {chat_id}",
        "msg": msg
    })

if __name__ == '__main__':
    app.run(debug=True)
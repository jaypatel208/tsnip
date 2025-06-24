from http.server import BaseHTTPRequestHandler
import json
import requests
import os
from dotenv import load_dotenv
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_API_KEY = os.getenv("SUPABASE_API_KEY")
SUPABASE_TABLE = os.getenv("ts_db")

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

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_url = urlparse(self.path)
        query_params = parse_qs(parsed_url.query)

        user = query_params.get('user', ['unknown'])[0]
        chat_id = query_params.get('chatId', ['id22'])[0]
        msg = query_params.get('msg', [''])[0]
        delay = query_params.get('delay', ['22'])[0]

        # User-supplied event timestamp (marking time)
        event_timestamp = datetime.now(timezone.utc).isoformat()

        # Save to Supabase
        insert_to_supabase(chat_id, delay, msg, user, event_timestamp)

        # Build response
        body = {
            "message": f"Timestamp marked at {event_timestamp} (delay {delay}s) by {user} with chat id {chat_id}",
            "msg": msg
        }

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(body).encode('utf-8'))

    def do_POST(self):
        # Handle POST requests the same way as GET for this endpoint
        self.do_GET()
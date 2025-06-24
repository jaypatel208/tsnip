from http.server import BaseHTTPRequestHandler
import json
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Parse the URL and query parameters
        parsed_url = urlparse(self.path)
        query_params = parse_qs(parsed_url.query)
        
        # Extract chatid and message from path
        # Expected format: /api/clip/chatid/message
        path_parts = parsed_url.path.strip('/').split('/')
        
        # For dynamic route [...params], the path will be /api/clip/[...params]/chatid/message
        # We need to find the chatid and message after the 'clip' part
        try:
            clip_index = path_parts.index('clip')
            if len(path_parts) > clip_index + 2:
                chatid = path_parts[clip_index + 1]
                msg = path_parts[clip_index + 2]
            else:
                chatid = 'unknown'
                msg = 'default'
        except (ValueError, IndexError):
            chatid = 'unknown'
            msg = 'default'
        
        # Extract delay from query parameters
        delay = query_params.get('delay', ['22'])[0]

        # Get current timestamp
        timestamp = datetime.now(timezone.utc).isoformat()

        # Create response body
        body = {
            "message": f"✅ Timestamp marked at {timestamp} (delay {delay}s) for chat {chatid}",
            "chatid": chatid,
            "msg": msg,
            "path_debug": path_parts  # Add this for debugging
        }

        # Send response
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(body).encode('utf-8'))

    def do_POST(self):
        # Handle POST requests the same way as GET for this endpoint
        self.do_GET()
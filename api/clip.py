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
        
        if len(path_parts) >= 4 and path_parts[0] == 'api' and path_parts[1] == 'clip':
            chatid = path_parts[2]
            msg = path_parts[3]
        else:
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
            "msg": msg
        }

        # Send response
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(body).encode('utf-8'))

    def do_POST(self):
        # Handle POST requests the same way as GET for this endpoint
        self.do_GET()
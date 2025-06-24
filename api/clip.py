from http.server import BaseHTTPRequestHandler
import json
from datetime import datetime
from urllib.parse import parse_qs, urlparse

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Parse the URL and query parameters
        parsed_url = urlparse(self.path)
        query_params = parse_qs(parsed_url.query)
        
        # Extract parameters with defaults
        user = query_params.get('user', ['unknown'])[0]
        msg = query_params.get('msg', [''])[0]
        delay = query_params.get('delay', ['22'])[0]

        # Get current timestamp
        timestamp = datetime.utcnow().isoformat()

        # Create response body
        body = {
            "message": f"✅ Timestamp marked at {timestamp} (delay {delay}s) by {user}",
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
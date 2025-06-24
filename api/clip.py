# api/clip.py
from http.server import BaseHTTPRequestHandler
import json
from datetime import datetime
from urllib.parse import parse_qs, urlparse

def handler(request):
    query_params = parse_qs(urlparse(request['url']).query)
    
    user = query_params.get('user', ['unknown'])[0]
    msg = query_params.get('msg', [''])[0]
    delay = query_params.get('delay', ['22'])[0]

    timestamp = datetime.utcnow().isoformat()

    body = {
        "message": f"✅ Timestamp marked at {timestamp} (delay {delay}s) by {user}",
        "msg": msg
    }

    return {
        "statusCode": 200,
        "headers": { "Content-Type": "application/json" },
        "body": json.dumps(body)
    }
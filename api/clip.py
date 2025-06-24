from datetime import datetime

def handler(request):
    query = request.get("query", {})
    user = query.get("user", "unknown")
    msg = query.get("msg", "")
    delay = query.get("delay", "22")

    timestamp = datetime.utcnow().isoformat()
    print(f"[TSnip] {timestamp} :: {user} requested timestamp with delay {delay}s :: msg: {msg}")

    return {
        "statusCode": 200,
        "body": f"✅ Timestamp marked at {timestamp} (delay {delay}s) by {user}"
    }
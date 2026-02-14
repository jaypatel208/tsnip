#!/usr/bin/env python3
"""CLI utility to obtain a YouTube OAuth refresh token.

Usage:
    python -m infrastructure.cli.refresh_token
"""

import sys
import os

# Ensure project root is on sys.path for absolute imports
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow

load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/youtube",
]


def main() -> None:
    client_id = os.getenv("YOUTUBE_CLIENT_ID")
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("Error: YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET must be set in .env")
        sys.exit(1)

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost:8080/"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)

    try:
        credentials = flow.run_local_server(
            port=8080, prompt="consent", access_type="offline"
        )
        print(f"Refresh token: {credentials.refresh_token}")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

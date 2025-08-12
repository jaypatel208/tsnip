#!/usr/bin/env python3
import os
from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# Load environment variables
load_dotenv()

# YouTube API scopes for posting comments
SCOPES = [
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/youtube",
]


def main():
    # Get credentials from .env
    client_id = os.getenv("YOUTUBE_CLIENT_ID")
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET")

    # Create client config
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost:8080/"],
        }
    }

    # Create flow
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)

    # Run the OAuth flow
    try:
        credentials = flow.run_local_server(
            port=8080, prompt="consent", access_type="offline"
        )
        print(f"Refresh token: {credentials.refresh_token}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()

"""Vercel entry point.

Vercel routes all requests to /api/clip.py (via vercel.json).
This file simply creates the Flask app from the DI container.
All logic lives in the layered architecture under core/, infrastructure/,
services/, and routes/.
"""

import sys
import os

# Ensure project root is on sys.path so absolute imports resolve on Vercel
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from container import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)

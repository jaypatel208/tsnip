"""Health check route — /health endpoint."""

from __future__ import annotations

from datetime import datetime
from flask import Blueprint, jsonify


def create_health_blueprint() -> Blueprint:
    bp = Blueprint("health", __name__)

    @bp.route("/health", methods=["GET"])
    def health_check():
        return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

    return bp

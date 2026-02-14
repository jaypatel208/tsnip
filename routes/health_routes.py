"""Health check route."""

from __future__ import annotations

from flask import Blueprint, jsonify
from loguru import logger


def create_health_blueprint() -> Blueprint:
    bp = Blueprint("health", __name__)

    @bp.route("/health", methods=["GET"])
    def health():
        logger.debug("Health check OK")
        return jsonify({"status": "ok"})

    return bp

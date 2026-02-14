"""Monitor-streams route — /api/monitor-streams endpoint."""

from __future__ import annotations

import logging
from flask import Blueprint, jsonify, request

from services.stream_monitor_service import StreamMonitorService

logger = logging.getLogger(__name__)


def create_monitor_blueprint(
    monitor_service: StreamMonitorService, cron_secret: str
) -> Blueprint:
    bp = Blueprint("monitor", __name__)

    @bp.route("/api/monitor-streams", methods=["GET", "POST"])
    def cron_monitor_streams():
        secret = request.args.get("secret") or request.headers.get("X-Cron-Secret")
        if not secret or secret != cron_secret:
            logger.warning("Unauthorized monitor-streams attempt")
            return jsonify({"error": "Unauthorized"}), 401

        try:
            logger.info("Running stream monitoring…")
            monitor_service.run()
            return jsonify({"message": "Stream monitoring executed successfully"}), 200
        except Exception as exc:
            logger.error("Stream monitoring error: %s", exc)
            return jsonify({"error": str(exc)}), 500

    return bp

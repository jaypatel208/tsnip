"""Monitor-streams route — cron-triggered endpoint."""

from __future__ import annotations

from flask import Blueprint, Response, request
from loguru import logger

from infrastructure.config import Settings
from services.stream_monitor_service import StreamMonitorService


def create_monitor_blueprint(
    monitor_service: StreamMonitorService, settings: Settings
) -> Blueprint:
    bp = Blueprint("monitor", __name__)

    @bp.route("/api/monitor-streams", methods=["GET"])
    def monitor_handler():
        secret = request.args.get("secret", "")
        if secret != settings.cron_secret:
            logger.warning(
                "Unauthorized monitor-streams attempt (ip={})",
                request.remote_addr,
            )
            return Response("Unauthorized", status=401)

        try:
            logger.info("Stream monitoring triggered (ip={})", request.remote_addr)
            monitor_service.run()
            logger.info("Stream monitoring completed successfully")
            return Response("OK", status=200)
        except Exception as exc:
            logger.exception("Stream monitoring error: {}", exc)
            return Response("Internal server error", status=500)

    return bp

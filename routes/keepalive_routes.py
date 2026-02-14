"""Discord keepalive route — /api/dc-keepalive endpoint."""

from __future__ import annotations

import logging
from flask import Blueprint, jsonify, request

from core.interfaces import DiscordNotifier

logger = logging.getLogger(__name__)


def create_keepalive_blueprint(discord: DiscordNotifier, cron_secret: str) -> Blueprint:
    bp = Blueprint("keepalive", __name__)

    @bp.route("/api/dc-keepalive", methods=["GET", "POST"])
    def discord_keepalive():
        client_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
        logger.info("Keepalive from %s", client_ip)

        provided = request.args.get("secret") or request.headers.get("X-Cron-Secret")
        if provided != cron_secret:
            logger.warning("Invalid keepalive secret from %s", client_ip)
            return (
                jsonify({"status": "error", "message": "Invalid or missing secret"}),
                401,
            )

        result = discord.keepalive_ping()
        status_code = 200 if result["status"] == "success" else 500
        return jsonify(result), status_code

    return bp

"""Discord keepalive route — cron-triggered endpoint."""

from __future__ import annotations

from flask import Blueprint, Response, jsonify, request
from loguru import logger

from infrastructure.config import Settings
from infrastructure.discord_client import DiscordClient


def create_keepalive_blueprint(discord: DiscordClient, settings: Settings) -> Blueprint:
    bp = Blueprint("keepalive", __name__)

    @bp.route("/api/dc-keepalive", methods=["GET"])
    def keepalive_handler():
        client_ip = request.remote_addr
        logger.info("Keepalive request from {}", client_ip)

        secret = request.args.get("secret", "")
        if secret != settings.cron_secret_dc_keep_alive:
            logger.warning("Invalid keepalive secret from {}", client_ip)
            return Response("Unauthorized", status=401)

        try:
            result = discord.keepalive_ping()
            logger.info("Keepalive result: {}", result.get("status"))
            return jsonify(result)
        except Exception as exc:
            logger.exception("Keepalive error: {}", exc)
            return Response("Internal server error", status=500)

    return bp

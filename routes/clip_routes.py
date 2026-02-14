"""Clip route — /api/clip endpoint.

Thin controller: extracts request params, validates, delegates to
ClipService, and returns the HTTP response.
"""

from __future__ import annotations

import logging
from flask import Blueprint, Response, request

from core.entities import ClipRequest
from services.clip_service import ClipService

logger = logging.getLogger(__name__)


def create_clip_blueprint(clip_service: ClipService) -> Blueprint:
    """Factory that builds the clip blueprint with injected service."""

    bp = Blueprint("clip", __name__)

    @bp.route("/api/clip", methods=["GET", "POST"])
    def clip_handler():
        user = request.args.get("user") or request.form.get("user")
        channel_id = request.args.get("channelid") or request.form.get("channelid")
        chat_id = request.args.get("chatId") or request.form.get("chatId")
        msg = request.args.get("msg") or request.form.get("msg") or ""
        delay_raw = request.args.get("delay") or request.form.get("delay")

        # --- required params ---
        if not all([user, channel_id, chat_id, delay_raw is not None]):
            logger.error("Missing required parameters")
            return Response(
                "Missing required parameters", mimetype="text/plain", status=400
            )

        try:
            delay = int(delay_raw)
        except (ValueError, TypeError):
            logger.error("Invalid delay: %s", delay_raw)
            return Response(
                "Invalid delay parameter", mimetype="text/plain", status=400
            )

        # --- format validation ---
        if not ClipService.validate_chat_id(chat_id):
            logger.error("Invalid chat_id: %s", chat_id)
            return Response("Invalid chat_id format", mimetype="text/plain", status=400)

        if not ClipService.validate_channel_id(channel_id):
            logger.error("Invalid channel_id: %s", channel_id)
            return Response(
                "Invalid channel_id format", mimetype="text/plain", status=400
            )

        # --- placeholder detection ---
        if any(ClipService.has_placeholder(v) for v in (user, channel_id, chat_id)) or (
            msg and ClipService.has_placeholder(msg)
        ):
            error = (
                "Error: Command not executed properly. "
                "Make sure to use this command in a stream chat "
                "where the bot variables can be resolved."
            )
            logger.error("Placeholder values detected")
            return Response(error, mimetype="text/plain", status=400)

        # --- delegate to service ---
        try:
            req = ClipRequest(
                user=user,
                channel_id=channel_id,
                chat_id=chat_id,
                delay=delay,
                message=msg,
            )
            comment = clip_service.create_clip(req)
            return Response(comment, mimetype="text/plain")
        except RuntimeError as exc:
            logger.error("Clip creation failed: %s", exc)
            return Response(
                "Error: Failed to save timestamp. Please try again.",
                mimetype="text/plain",
                status=500,
            )

    return bp

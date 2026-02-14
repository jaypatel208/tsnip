"""Clip route — thin HTTP handler delegating to ClipService."""

from __future__ import annotations

from flask import Blueprint, Response, request
from loguru import logger

from core.entities import ClipRequest
from services.clip_service import ClipService


def create_clip_blueprint(clip_service: ClipService) -> Blueprint:
    bp = Blueprint("clip", __name__)

    @bp.route("/api/clip", methods=["GET", "POST"])
    def clip_handler():
        user = request.values.get("user", "").strip()
        chat_id = request.values.get("chatId", "").strip()
        channel_id = request.values.get("channelid", "").strip()
        delay_raw = request.values.get("delay", "0").strip()
        message = (
            request.values.get("msg", "") or request.values.get("message", "")
        ).strip()

        # --- validation ---
        if not all([user, chat_id, channel_id]):
            logger.warning(
                "Missing params — user='{}', chat_id='{}', channel_id='{}'",
                user,
                chat_id,
                channel_id,
            )
            return Response("Missing required parameters", status=400)

        try:
            delay = int(delay_raw)
        except (ValueError, TypeError):
            logger.warning("Invalid delay value: {}", delay_raw)
            return Response("Invalid delay", status=400)

        if not clip_service.validate_chat_id(chat_id):
            logger.warning("Invalid chat_id: {} (len={})", chat_id[:20], len(chat_id))
            return Response("Invalid chat_id", status=400)

        if not clip_service.validate_channel_id(channel_id):
            logger.warning("Invalid channel_id: {}", channel_id)
            return Response("Invalid channel_id", status=400)

        # Nightbot placeholder detection
        if any(clip_service.has_placeholder(v) for v in (user, chat_id, channel_id)):
            logger.warning(
                "Placeholder values detected — user={}, chat_id={}, channel_id={}",
                user,
                chat_id,
                channel_id,
            )
            return Response(
                "Nightbot command is not configured correctly "
                "(receiving raw variable names instead of values).",
                status=400,
            )

        # --- execute ---
        try:
            logger.info(
                "Clip request — user={}, channel={}, delay={}",
                user,
                channel_id,
                delay,
            )
            req = ClipRequest(
                user=user,
                channel_id=channel_id,
                chat_id=chat_id,
                delay=delay,
                message=message,
                user_timestamp="",
            )
            comment = clip_service.create_clip(req)
            logger.info("Clip response sent for user={}", user)
            return Response(comment, mimetype="text/plain")
        except RuntimeError as exc:
            logger.error("Clip creation failed: {}", exc)
            return Response("Internal server error", status=500)
        except Exception as exc:
            logger.exception("Unexpected error in clip handler: {}", exc)
            return Response("Internal server error", status=500)

    return bp

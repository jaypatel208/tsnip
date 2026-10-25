"""The !ts flow: one database call, Discord on the right stream, the chat
reply, and the route around it.

Run from the repo root: python -m unittest discover -s tests -t .
"""

import json
import unittest
from pathlib import Path

from flask import Flask

from core.constants import (
    CHAT_MAX_LENGTH,
    COMMENT_FOOTER,
    GLIDE_LINK,
    MESSAGE_MAX_LENGTH,
)
from core.entities import ClipContext, ClipRequest, Video
from core.exceptions import ExternalServiceError, ValidationError
from routes.clip_routes import create_clip_blueprint
from services.clip_service import ClipService
from services.stream_monitor_service import _truncate

CHANNEL = "UC" + "a" * 22
OTHER = "UC" + "b" * 22
CHAT = "KicKGFVDUXVoeDFRVGJTWjd5dmFPYU5BZVp6ZxILSTlONzVTTkFpNXc"
VIDEO = Video(
    video_id="I9N75SNAi5w",
    title="Ranked grind",
    channel_id=CHANNEL,
    channel_title="Nyla",
    started_at="2025-10-25T10:00:00Z",
)


class Fakes:
    """Repository, YouTube and Discord in one, recording what was called."""

    def __init__(self, **ctx):
        self.ctx = ClipContext(
            **{"video_id": "I9N75SNAi5w", "created_at": "2025-10-25T10:05:00Z", **ctx}
        )
        self.calls = []
        self.sent = []
        self.error = None

    def record_timestamp(self, *args):
        self.calls.append(("record", args))
        if self.error:
            raise self.error
        return self.ctx

    def get_videos(self, ids):
        self.calls.append(("youtube", ids))
        return {VIDEO.video_id: VIDEO}

    def save_stream(self, video):
        self.calls.append(("save", video.video_id))
        return "pending"

    def send_clip_notification(self, *args):
        self.sent.append(args)
        return True


def service(fakes):
    return ClipService(fakes, fakes, fakes, tool_used="https://x.y")


def clip(fakes, user="@u", channel=CHANNEL, message="clutch"):
    req = ClipRequest(
        user=user, channel_id=channel, chat_id=CHAT, delay=22, message=message
    )
    return service(fakes).create_clip(req)


def line(message, template=None):
    return service(Fakes())._build_comment(template, "@abhiilash_k", 42, message)


class ChatLineTest(unittest.TestCase):
    def test_short_title_is_kept_and_the_link_ends_the_line(self):
        text = line("ghagra night")
        self.assertIn("'ghagra night'", text)
        self.assertTrue(text.endswith(GLIDE_LINK))
        self.assertLessEqual(len(text), CHAT_MAX_LENGTH)

    def test_a_long_title_is_shortened_never_the_link(self):
        text = line("boss fight " * 30)
        self.assertEqual(len(text), CHAT_MAX_LENGTH)
        self.assertIn("…'", text)
        self.assertTrue(text.endswith(GLIDE_LINK))

    def test_no_title(self):
        text = line("")
        self.assertNotIn("titled", text)
        self.assertTrue(text.endswith(GLIDE_LINK))

    def test_a_broken_template_falls_back_to_the_default(self):
        self.assertTrue(line("x", template="{nope}").endswith(GLIDE_LINK))

    def test_a_custom_template_is_used(self):
        self.assertEqual(line("x", template="hi {user}"), "hi @abhiilash_k")


class CreateClipTest(unittest.TestCase):
    def test_one_database_call_and_no_youtube_without_discord(self):
        fakes = Fakes()
        text = clip(fakes)
        self.assertEqual(fakes.calls, [("record", (CHAT, CHANNEL, "@u", "clutch", 22))])
        self.assertTrue(text.endswith(GLIDE_LINK))

    def test_discord_gets_this_chats_stream(self):
        fakes = Fakes(
            dc_channel_id="dc",
            title="Ranked grind",
            started_at="2025-10-25T10:00:00Z",
            owner_id=CHANNEL,
        )
        clip(fakes)
        self.assertEqual(len(fakes.calls), 1, "known stream: no YouTube call")
        (dc, video_id, title, message, user, ts) = fakes.sent[0]
        self.assertEqual(
            (dc, video_id, title, user), ("dc", "I9N75SNAi5w", "Ranked grind", "u")
        )
        # 10:05:00 minus the 22s delay, 10:00:00 start
        self.assertEqual(ts, "04:38")

    def test_the_first_ts_asks_youtube_and_saves_the_stream(self):
        fakes = Fakes(dc_channel_id="dc")
        clip(fakes)
        self.assertEqual([c[0] for c in fakes.calls], ["record", "youtube", "save"])
        self.assertEqual(len(fakes.sent), 1)

    def test_another_channels_stream_never_reaches_this_discord(self):
        fakes = Fakes(dc_channel_id="dc")
        clip(fakes, channel=OTHER)
        self.assertEqual(fakes.sent, [])

    def test_a_discord_failure_still_answers_chat(self):
        fakes = Fakes(dc_channel_id="dc")

        def boom(*args):
            raise RuntimeError("discord down")

        fakes.send_clip_notification = boom
        self.assertTrue(clip(fakes).endswith(GLIDE_LINK))


class ClipRouteTest(unittest.TestCase):
    """Flask → ClipService → fakes: the whole request path."""

    def setUp(self):
        self.fakes = Fakes()
        app = Flask(__name__)
        app.register_blueprint(create_clip_blueprint(service(self.fakes)))
        self.client = app.test_client()

    def get(self, **overrides):
        params = {
            "user": "@u",
            "chatId": CHAT,
            "channelid": CHANNEL,
            "msg": "clutch",
            "delay": "22",
            **overrides,
        }
        return self.client.get("/api/clip", query_string=params)

    def test_a_good_request_gets_the_chat_line(self):
        resp = self.get()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_data(as_text=True).endswith(GLIDE_LINK))

    def test_bad_input_is_refused_before_the_database(self):
        for overrides in (
            {"delay": "301"},
            {"delay": "-1"},
            {"delay": "soon"},
            {"channelid": "nope"},
            {"chatId": "short"},
            {"user": "$(user)"},
            {"user": ""},
        ):
            with self.subTest(overrides):
                self.assertEqual(self.get(**overrides).status_code, 400)
        self.assertEqual(self.fakes.calls, [])

    def test_a_long_title_is_cut_to_what_the_table_holds(self):
        self.get(msg="x" * 500)
        self.assertEqual(len(self.fakes.calls[0][1][3]), MESSAGE_MAX_LENGTH)

    def test_a_chat_with_no_video_is_a_400(self):
        self.fakes.error = ValidationError("no video")
        self.assertEqual(self.get().status_code, 400)

    def test_a_database_failure_is_a_500(self):
        self.fakes.error = ExternalServiceError("down")
        self.assertEqual(self.get().status_code, 500)


class CommentFooterTest(unittest.TestCase):
    def test_a_truncated_comment_keeps_the_footer_within_the_limit(self):
        body = _truncate("00:01 – (by someone)\n" * 1000, max_len=9000)
        self.assertTrue(body.endswith(COMMENT_FOOTER))
        self.assertLessEqual(len(body), 9000)

    def test_the_footer_names_glide_without_a_link(self):
        # Linked comments were public 8% of the time, unlinked ones 77%.
        self.assertIn("Glide", COMMENT_FOOTER)
        self.assertNotIn("http", COMMENT_FOOTER)


class VercelRedirectsTest(unittest.TestCase):
    def test_each_placement_has_its_own_campaign_and_runs_next_to_supabase(self):
        config = json.loads(Path("vercel.json").read_text())
        self.assertEqual(config["regions"], ["bom1"])
        redirects = {r["source"]: r for r in config["redirects"]}
        for source, placement in [
            ("/glide", "chat"),
            ("/glide/comment", "comment"),
            ("/glide/discord", "discord"),
        ]:
            r = redirects[source]
            self.assertFalse(r["permanent"])
            self.assertTrue(
                r["destination"].startswith(
                    "https://play.google.com/store/apps/details?id=dev.jay.glide&referrer="
                )
            )
            self.assertIn(f"utm_campaign%3Dtsnip_{placement}", r["destination"])


if __name__ == "__main__":
    unittest.main()

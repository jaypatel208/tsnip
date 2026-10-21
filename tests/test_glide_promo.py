"""Glide promotion and the parallel clip flow.

Run from the repo root: python -m unittest discover -s tests -t .
"""

import json
import threading
import unittest
from pathlib import Path

from core.constants import (
    CHAT_MAX_LENGTH,
    COMMENT_FOOTER,
    DEFAULT_COMMENT_TEMPLATE,
    GLIDE_LINK,
)
from core.entities import ClipRequest, CommentTemplate, LiveStreamInfo
from services.clip_service import ClipService
from services.stream_monitor_service import _truncate

CHANNEL = "UC" + "a" * 22


class FakeRepos:
    """Every repository and client the clip flow touches, recording calls."""

    def __init__(self, template=DEFAULT_COMMENT_TEMPLATE):
        self.template = template
        self.calls = []
        self.threads = set()

    def _record(self, name):
        self.calls.append(name)
        self.threads.add(threading.current_thread().name)

    def insert_clip(self, *args):
        self._record("insert")
        return True

    def chat_id_exists(self, chat_id):
        self._record("youtube")
        return True

    def get_discord_channel_id(self, channel_id):
        self._record("discord")

    def get_live_stream_info(self, channel_id):
        return LiveStreamInfo()

    def get_comment_template(self, channel_id):
        self._record("template")
        return CommentTemplate(template=self.template, is_custom=False)


def service(repos):
    return ClipService(repos, repos, repos, repos, repos, tool_used="https://x.y")


def line(repos, message):
    return service(repos)._build_comment(CHANNEL, "@abhiilash_k", 42, message)


class ChatLineTest(unittest.TestCase):
    def test_short_title_is_kept_and_the_link_ends_the_line(self):
        text = line(FakeRepos(), "ghagra night")
        self.assertIn("'ghagra night'", text)
        self.assertTrue(text.endswith(GLIDE_LINK))
        self.assertLessEqual(len(text), CHAT_MAX_LENGTH)

    def test_a_long_title_is_shortened_never_the_link(self):
        text = line(FakeRepos(), "boss fight " * 30)
        self.assertEqual(len(text), CHAT_MAX_LENGTH)
        self.assertIn("…'", text)
        self.assertTrue(text.endswith(GLIDE_LINK))

    def test_no_title(self):
        text = line(FakeRepos(), "")
        self.assertNotIn("titled", text)
        self.assertTrue(text.endswith(GLIDE_LINK))

    def test_a_broken_template_falls_back_to_the_default(self):
        text = line(FakeRepos(template="{nope}"), "x")
        self.assertTrue(text.endswith(GLIDE_LINK))


class CreateClipTest(unittest.TestCase):
    def test_every_step_still_runs_and_the_line_comes_back(self):
        repos = FakeRepos()
        req = ClipRequest(user="@u", channel_id=CHANNEL, chat_id="c" * 30, delay=22)
        text = service(repos).create_clip(req)
        self.assertEqual(repos.calls[0], "insert")
        self.assertCountEqual(repos.calls[1:], ["youtube", "discord", "template"])
        self.assertTrue(text.endswith(GLIDE_LINK))
        # The three steps after the insert ran off the request thread.
        self.assertGreater(len(repos.threads), 1)


class CommentFooterTest(unittest.TestCase):
    def test_a_truncated_comment_keeps_the_footer_within_the_limit(self):
        body = _truncate("00:01 – (by someone)\n" * 1000, max_len=9000)
        self.assertTrue(body.endswith(COMMENT_FOOTER))
        self.assertLessEqual(len(body), 9000)


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
        self.assertIn("/glide/comment", COMMENT_FOOTER)


if __name__ == "__main__":
    unittest.main()

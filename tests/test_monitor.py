"""The cron endpoint's secret and when the monitor gives up on a stream.

Run from the repo root: python -m unittest discover -s tests -t .
"""

import dataclasses
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from flask import Flask

from core.entities import UnmarkedStream, VideoStatus
from routes.monitor_routes import create_monitor_blueprint
from services.stream_monitor_service import GIVE_UP_AFTER, StreamMonitorService

SECRET = "s3cret"
# A Nightbot chat ID; it carries the video id I9N75SNAi5w.
CHAT = "KicKGFVDUXVoeDFRVGJTWjd5dmFPYU5BZVp6ZxILSTlONzVTTkFpNXc"


class FakeMonitor:
    def __init__(self):
        self.runs = 0

    def run(self):
        self.runs += 1


class MonitorRouteTest(unittest.TestCase):
    def setUp(self):
        self.monitor = FakeMonitor()
        app = Flask(__name__)
        app.register_blueprint(
            create_monitor_blueprint(self.monitor, SimpleNamespace(cron_secret=SECRET))
        )
        self.client = app.test_client()

    def test_the_header_secret_runs_the_monitor(self):
        resp = self.client.get(
            "/api/monitor-streams", headers={"X-Cron-Secret": SECRET}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.monitor.runs, 1)

    def test_the_query_secret_still_works(self):
        resp = self.client.get(f"/api/monitor-streams?secret={SECRET}")
        self.assertEqual(resp.status_code, 200)

    def test_a_wrong_or_missing_secret_is_refused(self):
        for headers in ({"X-Cron-Secret": "nope"}, {}):
            resp = self.client.get("/api/monitor-streams", headers=headers)
            self.assertEqual(resp.status_code, 401)
        self.assertEqual(self.monitor.runs, 0)


class FakeRepos:
    """Stream repo, timestamp repo and YouTube client in one, recording marks."""

    def __init__(self, stream, status):
        self.stream = stream
        self.status = status
        self.marked = []

    def get_unmarked_streams(self):
        return [self.stream]

    def check_video_status(self, video_id):
        return self.status

    def mark_as_processed(self, row_id, success=True, status="ended"):
        self.marked.append((row_id, success, status))
        return True

    def get_chat_messages(self, chat_id):
        return []


def stream_started(ago):
    start = (datetime.now(timezone.utc) - ago).isoformat()
    return UnmarkedStream(
        id="row",
        video_id="I9N75SNAi5w",
        chat_id=CHAT,
        channel_id="ch",
        stream_start_time=start,
    )


def run(stream, status):
    repos = FakeRepos(stream, status)
    StreamMonitorService(repos, repos, repos).run()
    return repos.marked


UNAVAILABLE = VideoStatus()  # not public, not unlisted, not live
NOT_COMMENTABLE = VideoStatus(is_public=True, can_comment=False, comments_disabled=True)
COMMENTABLE = VideoStatus(is_public=True, can_comment=True, comments_disabled=False)
LIVE = VideoStatus(is_live=True)


class GiveUpTest(unittest.TestCase):
    def test_a_fresh_stream_that_cant_be_commented_is_retried(self):
        for status in (UNAVAILABLE, NOT_COMMENTABLE, COMMENTABLE):
            self.assertEqual(run(stream_started(timedelta(hours=3)), status), [])

    def test_an_old_one_leaves_the_queue_with_its_reason(self):
        old = stream_started(GIVE_UP_AFTER + timedelta(hours=1))
        self.assertEqual(run(old, UNAVAILABLE), [("row", True, "unavailable")])
        self.assertEqual(run(old, NOT_COMMENTABLE), [("row", True, "not_commentable")])
        # Commentable but nobody timestamped anything.
        self.assertEqual(run(old, COMMENTABLE), [("row", True, "no_timestamps")])

    def test_a_live_stream_is_never_given_up(self):
        old = stream_started(GIVE_UP_AFTER * 10)
        self.assertEqual(run(old, LIVE), [])

    def test_no_start_time_keeps_it_queued(self):
        stream = dataclasses.replace(
            stream_started(timedelta(0)), stream_start_time=None
        )
        self.assertEqual(run(stream, UNAVAILABLE), [])



class WrongLinkTest(unittest.TestCase):
    def test_another_streams_chat_is_never_posted_on_this_video(self):
        stream = dataclasses.replace(
            stream_started(timedelta(hours=3)), video_id="jl81RdZAE9I"
        )
        self.assertEqual(run(stream, COMMENTABLE), [("row", True, "wrong_link")])


if __name__ == "__main__":
    unittest.main()

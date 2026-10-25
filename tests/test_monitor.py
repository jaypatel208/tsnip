"""The cron endpoints' secrets and the monitor: batching, giving up,
claiming before posting, and the time budget.

Run from the repo root: python -m unittest discover -s tests -t .
"""

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from flask import Flask

from core.entities import ChatMessage, QueuedStream, Video
from routes.keepalive_routes import create_keepalive_blueprint
from routes.monitor_routes import create_monitor_blueprint
from services.stream_monitor_service import (
    BATCH_SIZE,
    GIVE_UP_AFTER,
    TIME_BUDGET_SECONDS,
    StreamMonitorService,
)
from services.timestamp_formatter import comment_lines

SECRET = "s3cret"


class FakeMonitor:
    def __init__(self):
        self.runs = 0

    def run(self):
        self.runs += 1


class FakeDiscord:
    def keepalive_ping(self):
        return {"status": "success"}


class CronRouteTest(unittest.TestCase):
    def setUp(self):
        self.monitor = FakeMonitor()
        app = Flask(__name__)
        settings = SimpleNamespace(cron_secret=SECRET, cron_secret_dc_keep_alive=SECRET)
        app.register_blueprint(create_monitor_blueprint(self.monitor, settings))
        app.register_blueprint(create_keepalive_blueprint(FakeDiscord(), settings))
        self.client = app.test_client()

    def test_the_header_secret_runs_the_monitor(self):
        resp = self.client.get(
            "/api/monitor-streams", headers={"X-Cron-Secret": SECRET}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.monitor.runs, 1)

    def test_the_query_secret_still_works(self):
        for path in ("/api/monitor-streams", "/api/dc-keepalive"):
            resp = self.client.get(f"{path}?secret={SECRET}")
            self.assertEqual(resp.status_code, 200, path)

    def test_a_wrong_or_missing_secret_is_refused(self):
        for path in ("/api/monitor-streams", "/api/dc-keepalive"):
            for headers in ({"X-Cron-Secret": "nope"}, {}):
                resp = self.client.get(path, headers=headers)
                self.assertEqual(resp.status_code, 401, path)
        self.assertEqual(self.monitor.runs, 0)


def ago(delta):
    return (datetime.now(timezone.utc) - delta).isoformat()


def queued(video_id="I9N75SNAi5w", started=timedelta(hours=3), **kw):
    return QueuedStream(
        video_id=video_id,
        state=kw.pop("state", "pending"),
        created_at=kw.pop("created_at", ago(started or timedelta(0))),
        channel_id="UC" + "a" * 22,
        started_at=ago(started) if started is not None else None,
        **kw,
    )


def video(video_id="I9N75SNAi5w", **kw):
    fields = dict(
        video_id=video_id,
        title="t",
        channel_id="UC" + "a" * 22,
        channel_title="Nyla",
        started_at=ago(timedelta(hours=3)),
        visible=True,
    )
    return Video(**{**fields, **kw})


class Fakes:
    """Repository and YouTube client in one, recording what the monitor did."""

    def __init__(self, streams, videos, messages=(), outcome=("posted", "c1")):
        self.streams = streams
        self.videos = videos
        self.messages = list(messages)
        self.outcome = outcome
        self.lookups = []
        self.finished = []
        self.saved = []
        self.posted = []
        self.claimable = True
        self.save_state = "pending"
        self.member_only = False

    def get_queue(self):
        return self.streams

    def get_videos(self, ids):
        self.lookups.append(ids)
        if self.videos is None:
            return None
        return {v.video_id: v for v in self.videos if v.video_id in ids}

    def save_stream(self, video):
        self.saved.append(video.video_id)
        return self.save_state

    def is_member_only(self, video_id):
        return self.member_only

    def get_messages(self, video_id):
        return self.messages

    def claim(self, video_id):
        return self.claimable

    def post_comment(self, video_id, body):
        self.posted.append((video_id, body))
        return self.outcome

    def finish(self, video_id, state, comment_id=None):
        self.finished.append((video_id, state, comment_id))
        return True


def message(after, text="", user="@u", delay=0):
    """A !ts saved *after* seconds into a stream that started 3h ago."""
    created = datetime.now(timezone.utc) - timedelta(hours=3) + timedelta(seconds=after)
    return ChatMessage(
        message=text, user_name=user, created_at=created.isoformat(), delay=delay
    )


def run(fakes, clock=None):
    if clock:
        StreamMonitorService(fakes, fakes, clock=clock).run()
    else:
        StreamMonitorService(fakes, fakes).run()
    return fakes.finished


UNAVAILABLE = dict(visible=False)
FOR_KIDS = dict(made_for_kids=True)
LIVE = dict(is_live=True)


class GiveUpTest(unittest.TestCase):
    def test_a_fresh_stream_that_cant_be_commented_is_retried(self):
        for kw in (UNAVAILABLE, FOR_KIDS, {}):
            self.assertEqual(run(Fakes([queued()], [video(**kw)])), [])
        self.assertEqual(run(Fakes([queued()], [])), [], "gone from YouTube")

    def test_an_old_one_leaves_the_queue_with_its_reason(self):
        old = queued(started=GIVE_UP_AFTER + timedelta(hours=1))
        for kw, state in (
            (UNAVAILABLE, "unavailable"),
            (FOR_KIDS, "not_commentable"),
            ({}, "no_timestamps"),  # commentable but nobody timestamped
        ):
            self.assertEqual(
                run(Fakes([old], [video(**kw)])), [(old.video_id, state, None)]
            )

    def test_a_live_stream_is_never_given_up(self):
        old = queued(started=GIVE_UP_AFTER * 10)
        self.assertEqual(run(Fakes([old], [video(**LIVE)])), [])

    def test_with_no_start_time_the_first_timestamp_counts(self):
        never = dict(started=None, state="new")
        fresh = queued(created_at=ago(timedelta(hours=1)), **never)
        stale = queued(created_at=ago(GIVE_UP_AFTER * 2), **never)
        upcoming = dict(started_at=None, visible=False)
        self.assertEqual(run(Fakes([fresh], [video(**upcoming)])), [])
        self.assertEqual(
            run(Fakes([stale], [video(**upcoming)])),
            [(stale.video_id, "unavailable", None)],
        )

    def test_a_failed_youtube_call_never_counts_against_a_stream(self):
        old = queued(started=GIVE_UP_AFTER * 2)
        self.assertEqual(run(Fakes([old], None)), [])


class FirstLookTest(unittest.TestCase):
    def test_a_new_stream_is_saved_with_its_start_time_then_commented(self):
        stream = queued(started=None, state="new")
        fakes = Fakes([stream], [video()], messages=[message(60)])
        run(fakes)
        self.assertEqual(fakes.saved, [stream.video_id])
        self.assertIn("01:00", fakes.posted[0][1])

    def test_a_blacklisted_owner_is_skipped(self):
        fakes = Fakes([queued(state="new")], [video()], messages=[message(60)])
        fakes.save_state = "blacklisted"
        run(fakes)
        self.assertEqual(fakes.posted, [])

    def test_a_known_stream_is_not_saved_again(self):
        fakes = Fakes([queued()], [video()], messages=[message(60)])
        run(fakes)
        self.assertEqual(fakes.saved, [])


class PostingTest(unittest.TestCase):
    def fakes(self, **kw):
        return Fakes([queued()], [video()], messages=[message(60)], **kw)

    def test_posted_is_recorded_with_the_comment_id(self):
        fakes = self.fakes()
        self.assertEqual(run(fakes), [("I9N75SNAi5w", "posted", "c1")])

    def test_no_claim_no_post(self):
        fakes = self.fakes()
        fakes.claimable = False
        self.assertEqual(run(fakes), [])
        self.assertEqual(fakes.posted, [])

    def test_a_definite_failure_goes_back_in_the_queue(self):
        fakes = self.fakes(outcome=("failed", "quota"))
        self.assertEqual(run(fakes), [("I9N75SNAi5w", "pending", None)])

    def test_a_maybe_posted_comment_is_never_retried(self):
        fakes = self.fakes(outcome=("unknown", "timeout"))
        self.assertEqual(run(fakes), [], "stays 'posting' for a person to check")

    def test_a_rejection_records_why(self):
        fakes = self.fakes(outcome=("rejected", "member_only"))
        self.assertEqual(run(fakes), [("I9N75SNAi5w", "member_only", None)])

    def test_member_only_is_skipped_before_posting(self):
        fakes = self.fakes()
        fakes.member_only = True
        self.assertEqual(run(fakes), [("I9N75SNAi5w", "member_only", None)])
        self.assertEqual(fakes.posted, [])


class BatchAndBudgetTest(unittest.TestCase):
    def test_youtube_is_asked_50_streams_at_a_time(self):
        streams = [queued(video_id=f"{i:011d}") for i in range(120)]
        fakes = Fakes(streams, [])
        run(fakes)
        self.assertEqual(
            [len(ids) for ids in fakes.lookups], [BATCH_SIZE, BATCH_SIZE, 20]
        )

    def test_the_run_stops_before_vercel_kills_it(self):
        streams = [queued(video_id=f"{i:011d}") for i in range(5)]
        fakes = Fakes(
            streams,
            [video(video_id=s.video_id) for s in streams],
            messages=[message(60)],
        )
        ticks = iter([0, 1, 2, TIME_BUDGET_SECONDS + 1])
        run(fakes, clock=lambda: next(ticks, TIME_BUDGET_SECONDS + 1))
        self.assertEqual(len(fakes.posted), 2)


class CommentLinesTest(unittest.TestCase):
    def test_lines_are_in_stream_order_whatever_order_they_were_saved(self):
        # Saved later but with a bigger delay, so it points earlier.
        body = comment_lines([(300, "late", "a"), (100, "early", "b")])
        self.assertEqual(body, ["01:40 – _early_ (by b)", "05:00 – _late_ (by a)"])

    def test_one_moment_spammed_by_many_becomes_one_line(self):
        lines = comment_lines(
            [(60, "ace", "a"), (64, "", "b"), (69, "ACE!!", "c"), (66, "ace", "a")]
        )
        self.assertEqual(lines, ["01:00 – _ace / ACE!!_ (by a, b, c)"])

    def test_the_window_is_anchored_so_lines_dont_chain_forever(self):
        lines = comment_lines([(0, "", "a"), (9, "", "b"), (18, "", "c")])
        self.assertEqual(lines, ["00:00 – (by a, b)", "00:18 – (by c)"])

    def test_the_monitor_merges_and_strips_emojis_and_at(self):
        fakes = Fakes(
            [queued()],
            [video()],
            messages=[message(60, "gg :_wave:", "@x"), message(65, "", "@y")],
        )
        run(fakes)
        self.assertIn("01:00 – _gg_ (by x, y)", fakes.posted[0][1])


if __name__ == "__main__":
    unittest.main()

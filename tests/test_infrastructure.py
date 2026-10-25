"""Supabase and YouTube adapters, with the network faked out.

Run from the repo root: python -m unittest discover -s tests -t .
"""

import json
import unittest
from types import SimpleNamespace

import requests
from googleapiclient.errors import HttpError

from core.entities import ClipContext
from core.exceptions import ExternalServiceError, ValidationError
from infrastructure.supabase_client import SupabaseClient
from infrastructure.supabase_repository import SupabaseRepository
from infrastructure.youtube_api_client import YouTubeApiClient, _to_video


def response(status, body):
    resp = requests.Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    resp.url = "https://x.supabase.co/rest/v1/x"
    return resp


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        return self.responses.pop(0)


def repo(*responses):
    client = SupabaseClient(
        SimpleNamespace(supabase_url="https://x.supabase.co", supabase_api_key="k")
    )
    client._session = FakeSession(*responses)
    return SupabaseRepository(client), client._session


CTX = {
    "video_id": "I9N75SNAi5w",
    "created_at": "2025-10-25T10:05:00+00:00",
    "title": None,
    "started_at": None,
    "owner_id": None,
    "template": None,
    "dc_channel_id": None,
}


class SupabaseRepositoryTest(unittest.TestCase):
    def test_a_ts_is_one_rpc_call(self):
        r, session = repo(response(200, CTX))
        ctx = r.record_timestamp("chat", "UCx", "u", "m", 22)
        self.assertEqual(ctx, ClipContext(**CTX))
        method, url, kwargs = session.requests[0]
        self.assertEqual(
            (method, url),
            ("POST", "https://x.supabase.co/rest/v1/rpc/record_timestamp"),
        )
        self.assertEqual(kwargs["json"]["p_chat_id"], "chat")

    def test_a_refused_chat_is_a_validation_error_and_an_outage_is_not(self):
        r, _ = repo(response(400, {"code": "22023"}))
        with self.assertRaises(ValidationError):
            r.record_timestamp("chat", "UCx", "u", "m", 22)
        r, _ = repo(response(500, {}))
        with self.assertRaises(ExternalServiceError):
            r.record_timestamp("chat", "UCx", "u", "m", 22)

    def test_filter_values_never_land_in_the_url_unencoded(self):
        # v1 built "video_id=eq.{value}" by hand, so a value could smuggle in
        # filters of its own. Now values only travel in params.
        r, session = repo(response(200, []))
        r.get_messages("x&or=(state.eq.posted)")
        _, url, kwargs = session.requests[0]
        self.assertEqual(url, "https://x.supabase.co/rest/v1/timestamps")
        self.assertEqual(kwargs["params"]["video_id"], "eq.x&or=(state.eq.posted)")
        prepared = requests.Request("GET", url, params=kwargs["params"]).prepare()
        self.assertNotIn("&or=", prepared.url)

    def test_messages_come_in_order(self):
        r, session = repo(response(200, []))
        r.get_messages("v")
        self.assertEqual(session.requests[0][2]["params"]["order"], "created_at.asc")

    def test_a_claim_only_takes_a_pending_stream(self):
        r, session = repo(response(200, [{"video_id": "v"}]), response(200, []))
        self.assertTrue(r.claim("v"))
        self.assertFalse(r.claim("v"), "nothing updated: someone else has it")
        method, _, kwargs = session.requests[0]
        self.assertEqual(method, "PATCH")
        self.assertEqual(kwargs["params"], {"video_id": "eq.v", "state": "eq.pending"})
        self.assertEqual(kwargs["json"], {"state": "posting"})

    def test_a_failed_read_is_an_empty_queue_not_a_crash(self):
        r, _ = repo(response(503, {}))
        self.assertEqual(r.get_queue(), [])


def http_error(status, reason):
    resp = SimpleNamespace(status=status, reason="x")
    body = json.dumps(
        {"error": {"message": "m", "errors": [{"reason": reason}]}}
    ).encode()
    return HttpError(resp, body)


class FakeYouTube:
    def __init__(self, error=None):
        self.error = error
        self.calls = 0

    def commentThreads(self):
        return self

    def insert(self, **kwargs):
        return self

    def execute(self):
        self.calls += 1
        if self.error:
            raise self.error
        return {"id": "c1"}


def post(error=None):
    client = YouTubeApiClient.__new__(YouTubeApiClient)
    yt = FakeYouTube(error)
    client._get_authenticated_client = lambda: yt
    return client.post_comment("v", "body"), yt.calls


class PostCommentTest(unittest.TestCase):
    def test_each_answer_is_classified_and_nothing_is_sent_twice(self):
        cases = [
            (None, ("posted", "c1")),
            (http_error(403, "commentsDisabled"), ("rejected", "not_commentable")),
            (http_error(403, "forbidden"), ("rejected", "member_only")),
            (http_error(403, "quotaExceeded"), ("failed", "quota")),
            (http_error(503, "backendError"), ("unknown",)),
            (TimeoutError("read timed out"), ("unknown",)),
        ]
        for error, expected in cases:
            with self.subTest(error=error):
                outcome, calls = post(error)
                self.assertEqual(outcome[: len(expected)], expected)
                self.assertEqual(calls, 1)

    def test_no_oauth_means_nothing_was_sent(self):
        client = YouTubeApiClient.__new__(YouTubeApiClient)

        def broken():
            raise RuntimeError("bad refresh token")

        client._get_authenticated_client = broken
        self.assertEqual(client.post_comment("v", "b"), ("failed", "oauth"))


class ToVideoTest(unittest.TestCase):
    def item(self, broadcast="none", details=None, privacy="public"):
        return {
            "id": "v",
            "snippet": {
                "title": "T",
                "channelId": "UCx",
                "channelTitle": "C",
                "liveBroadcastContent": broadcast,
            },
            "status": {"privacyStatus": privacy},
            "liveStreamingDetails": details or {},
        }

    def test_an_ended_stream(self):
        v = _to_video(self.item(details={"actualStartTime": "s", "actualEndTime": "e"}))
        self.assertEqual((v.started_at, v.is_live, v.visible), ("s", False, True))

    def test_started_without_an_end_is_still_live(self):
        self.assertTrue(_to_video(self.item(details={"actualStartTime": "s"})).is_live)
        self.assertTrue(_to_video(self.item(broadcast="upcoming")).is_live)

    def test_private_is_not_visible(self):
        self.assertFalse(_to_video(self.item(privacy="private")).visible)
        self.assertTrue(_to_video(self.item(privacy="unlisted")).visible)


if __name__ == "__main__":
    unittest.main()

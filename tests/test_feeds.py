from __future__ import annotations

import io
import json

from brick_panel.feeds import from_settings
from brick_panel.feeds import JsonFeed
from brick_panel.metrics import Metrics


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def opener(answers):
    """urlopen that returns (or raises) the next answer each call."""
    calls = []

    def open_(request, timeout):
        calls.append(request.full_url)
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return io.BytesIO(json.dumps(answer).encode())

    open_.calls = calls
    return open_


def test_feed_keeps_last_answer_until_stale():
    clock, metrics = Clock(), Metrics()
    feed = JsonFeed("board", "http://x/api/state", 30, 300, metrics, opener([{"a": 1}, OSError("down")]), clock)
    assert feed.fresh() is None and feed.age() is None
    assert feed.poll() is True
    assert feed.fresh() == {"a": 1}
    assert metrics.get("panel_feed_up", feed="board") == 1

    clock.t += 200
    assert feed.poll() is False
    assert feed.fresh() == {"a": 1}  # still worth showing
    assert metrics.get("panel_feed_up", feed="board") == 0
    assert metrics.get("panel_feed_requests_total", feed="board", result="error") == 1

    clock.t += 101
    assert feed.fresh() is None  # too old to trust
    assert feed.data == {"a": 1}


def test_bad_json_is_an_error():
    feed = JsonFeed("x", "http://x", 30, 300, opener=lambda request, timeout: io.BytesIO(b"not json"))
    assert feed.poll() is False


def test_from_settings_skips_empty_urls(settings):
    settings["feeds"]["sources"]["overwatch"]["url"] = ""
    feeds = from_settings(settings, Metrics())
    assert set(feeds) == {"board", "prometheus"}
    assert feeds["board"].stale_seconds == settings["feeds"]["stale_seconds"]

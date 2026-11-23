from __future__ import annotations

import logging

import pytest

from brick_panel import rum
from brick_panel.metrics import Metrics

SCREENS = ["home", "weather"]


def test_a_report_becomes_metrics():
    m = Metrics()
    body = {
        "taps": [40, 150, 320, "junk", -5],
        "long_tasks": [60, 140],
        "idle": {"screen": "home", "frames": [16.7, 16.6, 33.4, 16.7]},
        "polls": [20, 30],
        "heap_bytes": 12_000_000,
        "uptime_s": 600,
        "loaded": True,
    }
    rum.record(m, body, late_after_ms=25, screens=SCREENS)
    assert [m.get("panel_rum_taps_total", speed=s) for s in ("fast", "ok", "slow")] == [1, 1, 1]
    assert m.get("panel_rum_tap_worst_seconds") == 0.32
    assert m.get("panel_rum_long_tasks_total") == 2
    assert m.get("panel_rum_long_task_seconds_total") == 0.2
    assert m.get("panel_rum_idle_frames_total", screen="home", result="on_time") == 3
    assert m.get("panel_rum_idle_frames_total", screen="home", result="late") == 1
    assert m.get("panel_rum_polls_total") == 2
    assert m.get("panel_rum_poll_seconds_total") == 0.05
    assert m.get("panel_rum_heap_bytes") == 12_000_000
    assert m.get("panel_rum_page_uptime_seconds") == 600
    assert m.get("panel_rum_page_loads_total") == 1


def test_junk_is_ignored():
    m = Metrics()
    rum.record(
        m,
        {"taps": "x", "idle": {"screen": "nowhere", "frames": [16]}, "heap_bytes": True, "uptime_s": -1},
        late_after_ms=25,
        screens=SCREENS,
    )
    assert m.get("panel_rum_idle_frames_total", screen="nowhere", result="on_time") == 0
    assert m.get("panel_rum_heap_bytes") == 0
    assert m.get("panel_rum_page_loads_total") == 0


def test_errors_are_counted_and_logged_a_few_at_a_time(caplog):
    m = Metrics()
    errors = [{"message": f"boom {i}", "source": "/static/panel.js", "line": i} for i in range(8)]
    with caplog.at_level(logging.WARNING):
        rum.record(m, {"errors": errors}, late_after_ms=25, screens=SCREENS)
    assert m.get("panel_rum_errors_total") == 8
    assert len(caplog.records) == rum.MAX_ERRORS_LOGGED
    assert "boom 0" in caplog.records[0].getMessage()


@pytest.mark.parametrize(("ms", "speed"), [(0, "fast"), (99.9, "fast"), (100, "ok"), (199.9, "ok"), (200, "slow")])
def test_tap_speed(ms, speed):
    assert rum.tap_speed(ms) == speed

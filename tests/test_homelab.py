from __future__ import annotations

from datetime import datetime
from datetime import UTC

import pytest

from brick_panel import homelab


def alert(name, severity="warning", state="firing", since="2026-11-22T20:00:00Z", **labels):
    return {"state": state, "activeAt": since, "labels": {"alertname": name, "severity": severity, **labels}}


def prom(*alerts):
    return {"data": {"alerts": list(alerts)}}


def test_words():
    assert homelab.words("KubeProxyDown") == "KUBE PROXY DOWN"
    assert homelab.words("CPUThrottlingHigh") == "CPU THROTTLING HIGH"


def test_infra_alerts_skips_plumbing_pending_and_duplicates():
    data = prom(
        alert("Watchdog", "none"),
        alert("TargetDown", job="lcars"),
        alert("TargetDown", job="lcars"),
        alert("NodeDown", "critical", instance="brick666", since="2026-11-22T21:00:00Z"),
        alert("DiskFilling", state="pending"),
        alert("Odd", "page"),
    )
    assert [(a["text"], a["severity"]) for a in homelab.infra_alerts(data)] == [
        ("NODE DOWN BRICK666", "critical"),
        ("TARGET DOWN LCARS", "warning"),
    ]


def test_infra_alerts_none_until_prometheus_answers():
    assert homelab.infra_alerts(None) is None
    assert homelab.infra_alerts(["not", "a", "dict"]) is None


def test_overwatch_feeds_and_recent():
    now = 10_000
    data = {
        "feeds": [
            {
                "name": "scanner",
                "state": {
                    "panel": {"headline": {"word": "alert", "line": "tracker following", "severity": 3}},
                    "alerts": [
                        {"label": "AirTag", "detail": "seen twice", "at": now - 60},
                        {"kind": "crowd", "count": 9, "at": now - 900},
                        {"label": "old", "at": now - 4000},
                    ],
                },
            },
            {"name": "wifi", "error": "timeout"},
        ]
    }
    view = homelab.overwatch(data, now)
    assert view["feeds"] == [
        {"name": "SCANNER", "word": "ALERT", "line": "TRACKER FOLLOWING", "severity": 3},
        {"name": "WIFI", "word": "NO SIGNAL", "line": "", "severity": 3},
    ]
    assert [(r["text"], r["live"]) for r in view["recent"]] == [("AIRTAG SEEN TWICE", True), ("CROWD 9 NEARBY", False)]


def test_weather_alerts_worst_first_with_timestamps():
    ends = datetime(2026, 11, 23, 6, 0, tzinfo=UTC)
    out = homelab.weather_alerts(
        [
            {"event": "WIND ADVISORY", "severity": "Moderate", "ends": None},
            {"event": "TORNADO WARNING", "severity": "Extreme", "ends": ends},
        ]
    )
    assert [a["event"] for a in out] == ["TORNADO WARNING", "WIND ADVISORY"]
    assert out[0]["ends"] == ends.timestamp()
    assert homelab.weather_alerts(None) is None


GREEN_WATCH = {"feeds": [{"severity": 0}], "recent": []}


@pytest.mark.parametrize(
    ("infra", "watch", "weather", "expected"),
    [
        (None, None, None, "UNKNOWN"),
        ([], None, None, "GREEN"),
        ([{"severity": "warning"}], GREEN_WATCH, [], "YELLOW"),
        ([{"severity": "critical"}], GREEN_WATCH, [], "RED"),
        ([], {"feeds": [{"severity": 2}], "recent": []}, [], "YELLOW"),
        ([], {"feeds": [], "recent": [{"live": True}]}, [], "RED"),
        ([], None, [{"severity": "Severe"}], "YELLOW"),
        ([], None, [{"severity": "Extreme"}], "RED"),
        ([], None, [{"severity": "Minor"}], "GREEN"),
    ],
)
def test_condition(infra, watch, weather, expected):
    assert homelab.condition(infra, watch, weather) == expected


def test_alerts_view_counts_what_needs_a_look():
    view = homelab.alerts_view(
        prom(alert("TargetDown", job="lcars")),
        {"feeds": [{"name": "wifi", "state": {"panel": {"headline": {"severity": 2}}}}]},
        [{"event": "FROST ADVISORY", "severity": "Minor"}],
        now=0,
    )
    assert view["condition"] == "YELLOW"
    assert view["count"] == 3


def test_brick_view():
    board = {
        "overall": "warn",
        "groups": {
            "cluster": {
                "state": "warn",
                "checks": [
                    {"name": "brick420", "state": "ok", "detail": "Ready"},
                    {"name": "scrape", "state": "warn", "detail": "down"},
                    {"name": "api", "state": "fail", "detail": "refused"},
                ],
            },
        },
        "vitals": [
            {"node": "brick420", "cpu": 4.5, "mem": 25.7, "temp": 48.0, "disk": 38.5, "temp_warn": False, "x": 1}
        ],
        "recent": [{"job": f"j{i}", "number": i, "state": "ok", "what": "passed"} for i in range(9)],
        "shipped": [{"name": "traefik", "version": "3.7.8", "age": "2h", "state": "ok"}],
        "host": {"internet": True},
    }
    view = homelab.brick_view(board)
    group = view["groups"][0]
    assert (group["name"], group["ok"], group["total"]) == ("CLUSTER", 1, 3)
    assert [p["name"] for p in group["problems"]] == ["api", "scrape"]
    assert "x" not in view["vitals"][0]
    assert len(view["recent"]) == homelab.RECENT_BUILDS
    assert view["internet"] is True


def test_brick_view_odd_states_and_no_board():
    assert homelab.brick_view(None) is None
    view = homelab.brick_view({"overall": "weird", "groups": {"x": "not a group"}, "vitals": ["junk"]})
    assert view["overall"] == "unknown"
    assert view["groups"] == [] and view["vitals"] == []

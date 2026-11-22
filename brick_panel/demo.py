"""Made-up data for trying the page on a laptop: python3 -m brick_panel --demo."""

from __future__ import annotations

import time

from .feeds import DemoFeed


class DemoWeather:
    point = (0.0, 0.0)
    source = "demo"
    error = ""

    def __init__(self) -> None:
        self.updated = time.time()

    def current(self) -> dict:
        return {
            "temperature": 58.6,
            "condition": "LIGHT RAIN",
            "humidity": 87,
            "wind_mph": 9,
            "wind_from": "SW",
            "time": None,
        }

    def periods(self) -> list[dict]:
        return [
            {"name": "TONIGHT", "temperature": 49, "forecast": "RAIN SHOWERS LIKELY", "rain": 70, "day": False},
            {"name": "MONDAY", "temperature": 61, "forecast": "PARTLY SUNNY", "rain": 20, "day": True},
            {"name": "MONDAY NIGHT", "temperature": 44, "forecast": "MOSTLY CLEAR", "rain": None, "day": False},
            {"name": "TUESDAY", "temperature": 57, "forecast": "SUNNY", "rain": None, "day": True},
            {"name": "TUESDAY NIGHT", "temperature": 41, "forecast": "PARTLY CLOUDY", "rain": 10, "day": False},
            {"name": "WEDNESDAY", "temperature": 52, "forecast": "CHANCE THUNDERSTORMS", "rain": 40, "day": True},
        ]

    def alerts(self) -> list:
        return []

    def age(self) -> float:
        return time.time() - self.updated

    def start(self) -> None:
        pass


def _check(group: str, name: str, detail: str, state: str = "ok") -> dict:
    return {"group": group, "name": name, "state": state, "detail": detail}


def demo_feeds() -> dict[str, DemoFeed]:
    """A homelab with something to show on every screen: a warning on the
    board, one firing alert, overwatch learning."""
    now = time.time()
    board = {
        "overall": "warn",
        "groups": {
            "cluster": {
                "state": "warn",
                "checks": [
                    _check("cluster", "brick420", "Ready"),
                    _check("cluster", "brick666", "Ready"),
                    _check("cluster", "brick2000", "Ready"),
                    _check("cluster", "control plane", "API up"),
                    _check("cluster", "scrape lcars", "down 4m", "warn"),
                ],
            },
            "builds": {"state": "ok", "checks": [_check("builds", f"job-{i}", "passed") for i in range(18)]},
            "argocd": {"state": "ok", "checks": [_check("argocd", "apps", "22/22 synced and healthy")]},
            "services": {
                "state": "ok",
                "checks": [
                    _check("services", h, "no failed units")
                    for h in ("brick9000", "brick1982", "brick2000", "brick420")
                ],
            },
            "wigle": {"state": "ok", "checks": [_check("wigle", "last sync", "OK, 3h ago")]},
        },
        "vitals": [
            {"node": "brick420", "cpu": 4.5, "mem": 25.7, "temp": 48.0, "disk": 38.5, "temp_warn": False},
            {"node": "brick666", "cpu": 5.2, "mem": 25.1, "temp": 56.8, "disk": 14.1, "temp_warn": False},
            {"node": "brick2000", "cpu": 16.9, "mem": 59.6, "temp": 49.0, "disk": 53.4, "temp_warn": False},
            {"node": "brick9000", "cpu": 24.8, "mem": 13.4, "temp": 71.2, "disk": 70.3, "temp_warn": True},
        ],
        "recent": [
            {"job": "mirror-repos", "number": 544, "state": "ok", "what": "passed 3m ago"},
            {"job": "deploy-brick1982", "number": 88, "state": "ok", "what": "passed 41m ago"},
            {"job": "build-image", "number": 1203, "state": "fail", "what": "failed 2h ago"},
            {"job": "check-all", "number": 310, "state": "ok", "what": "passed 4h ago"},
        ],
        "shipped": [
            {"name": "traefik", "version": "3.7.8", "age": "2h", "state": "ok"},
            {"name": "presto", "version": "1.4.0", "age": "1d", "state": "ok"},
        ],
        "host": {"internet": True},
    }
    prometheus = {
        "data": {
            "alerts": [
                {
                    "state": "firing",
                    "activeAt": "2026-11-22T20:01:00Z",
                    "labels": {"alertname": "TargetDown", "severity": "warning", "job": "lcars"},
                },
                {"state": "firing", "labels": {"alertname": "Watchdog", "severity": "none"}},
            ]
        }
    }
    overwatch = {
        "feeds": [
            {
                "name": "scanner",
                "error": "",
                "state": {
                    "panel": {"headline": {"word": "all clear", "line": "8 devices, all known", "severity": 0}},
                    "alerts": [{"kind": "tracker", "label": "AirTag", "detail": "seen twice", "at": now - 900}],
                },
            },
            {
                "name": "wifi",
                "error": "",
                "state": {
                    "panel": {"headline": {"word": "learning", "line": "day 3 of 7", "severity": 1}},
                    "alerts": [],
                },
            },
        ]
    }
    return {"board": DemoFeed(board), "prometheus": DemoFeed(prometheus), "overwatch": DemoFeed(overwatch)}

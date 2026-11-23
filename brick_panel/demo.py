"""Made-up data for trying the page on a laptop: python3 -m brick_panel --demo."""

from __future__ import annotations

import time
from datetime import datetime
from datetime import timedelta

from . import calendar as cal
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


def demo_settings(settings: dict, night: bool = False) -> dict:
    """The settings --demo needs: a code (1982), two lights and a calendar,
    unless the settings have their own; never dark, unless night (then always)."""
    settings["climate"]["pin"] = settings["climate"]["pin"] or "1982"
    settings["lights"]["entities"] = settings["lights"]["entities"] or {
        "light.lamp": "Desk",
        "light.bedside": "Bedside",
    }
    settings["calendar"]["entities"] = settings["calendar"]["entities"] or ["calendar.demo"]
    settings["night"]["window"] = "00:00-23:59" if night else ""
    return settings


def demo_events(now: datetime) -> list[dict]:
    """A month with something on most screens' worth of days: one starting
    soon, one running, one over, an all-day, a trip over three days."""
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)

    def at(days: int, hour: float, minutes: float, summary: str, **more: str) -> dict:
        start = day + timedelta(days=days, hours=hour)
        return {
            "summary": summary,
            "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": (start + timedelta(minutes=minutes)).isoformat()},
            **more,
        }

    def all_day(days: int, length: int, summary: str) -> dict:
        start = (day + timedelta(days=days)).date()
        return {
            "summary": summary,
            "start": {"date": start.isoformat()},
            "end": {"date": (start + timedelta(days=length)).isoformat()},
        }

    soon = now + timedelta(minutes=12)
    raw = [
        all_day(0, 1, "Recycling out"),
        at(0, 7.5, 30, "Coffee with the neighbours"),
        {
            "summary": "Dentist",
            "start": {"dateTime": soon.isoformat()},
            "end": {"dateTime": (soon + timedelta(minutes=45)).isoformat()},
            "location": "Suite 200, the clinic on the corner",
            "description": "<p>Bring the insurance card.</p><p>Cleaning and X-rays.</p>",
        },
        at(0, 19, 120, "Movie night"),
        at(1, 9, 60, "Plumber visit", description="Kitchen sink, back left."),
        at(1, 18.5, 90, "Climbing gym"),
        all_day(3, 3, "Trip to the coast"),
        at(5, 12, 60, "Lunch with Sam"),
        at(8, 10, 30, "Car service"),
        at(8, 15, 60, "Haircut"),
        at(8, 17, 60, "Book club"),
        at(8, 20, 60, "Call home"),
        at(12, 14, 60, "Vet: annual checkup"),
        at(17, 8, 600, "Work offsite"),
        at(23, 19, 180, "Concert"),
        at(-2, 10, 60, "Farmers market"),
    ]
    return [e for e in (cal.parse(r, "calendar.demo", now.tzinfo) for r in raw) if e]


DEMO_ITEMS = [
    "Milk",
    "Eggs",
    "Coffee beans",
    "Dish soap",
    "Bananas",
    "Tortillas",
    "Olive oil",
    "AA batteries",
    "Cat food",
    "Lemons",
    "Sourdough",
    "Paper towels",
    "Greek yogurt",
    "Spinach",
]


class DemoRoom:
    """The bedroom, made up."""

    temperature, humidity = 71.4, 41.0

    def fresh(self) -> bool:
        return True

    def document(self) -> dict:
        return {"up": True, "temperature_f": self.temperature, "humidity": self.humidity}

    def start(self) -> None:
        pass


class DemoHomeAssistant:
    """Home Assistant, made up, that does what it's told: a heating
    thermostat, its guardrails, and the settings' lights."""

    connected, error, unit = True, "", "°F"

    def __init__(self, settings: dict) -> None:
        c = settings["climate"]
        self.thermostat = c["thermostat"]
        self.states = {
            self.thermostat: {
                "state": "heat",
                "attributes": {
                    "temperature": 70,
                    "target_temp_low": None,
                    "target_temp_high": None,
                    "current_temperature": 68.5,
                    "hvac_action": "heating",
                    "hvac_modes": ["heat", "cool", "heat_cool", "off"],
                },
            },
            c["lock_entity"]: {"state": "normal", "attributes": {}},
            c["setpoint_min_entity"]: {"state": "64", "attributes": {}},
            c["setpoint_max_entity"]: {"state": "76", "attributes": {}},
        }
        for i, entity in enumerate(settings["lights"]["entities"]):
            on = i == 0
            self.states[entity] = {"state": "on" if on else "off", "attributes": {"brightness": 178 if on else None}}
        self._events = demo_events(self.now())
        self._items = [
            {"uid": f"item-{i}", "summary": name, "status": "completed" if i in (2, 6) else "needs_action"}
            for i, name in enumerate(DEMO_ITEMS)
        ]

    def now(self) -> datetime:
        return datetime.now().astimezone()

    def events(self) -> list[dict]:
        return list(self._events)

    def events_age(self) -> float:
        return 0.0

    def items(self) -> list[dict]:
        return [dict(i) for i in self._items]

    def set_item_status(self, uid: str, status: str) -> None:
        for item in self._items:
            if item["uid"] == uid:
                item["status"] = status

    def state(self, entity_id: str) -> dict | None:
        return self.states.get(entity_id)

    def attrs(self, entity_id: str) -> dict:
        return dict((self.states.get(entity_id) or {}).get("attributes") or {})

    def value(self, entity_id: str, default: str | None = None) -> str | None:
        return (self.states.get(entity_id) or {}).get("state", default)

    def number(self, entity_id: str, default: float) -> float:
        try:
            return float(self.value(entity_id))
        except (TypeError, ValueError):
            return default

    def call(self, domain: str, service: str, **data: object) -> None:
        entity = data.pop("entity_id")
        if domain == "todo":
            self.set_item_status(data["item"], data["status"])
            return
        s = self.states[entity]
        attrs = s["attributes"]
        if service == "set_temperature":
            attrs.update(data)
        elif service == "set_hvac_mode":
            mode = data["hvac_mode"]
            s["state"] = mode
            auto = mode == "heat_cool"
            attrs.update(
                temperature=None if auto or mode == "off" else 70,
                target_temp_low=67 if auto else None,
                target_temp_high=74 if auto else None,
                hvac_action={"heat": "heating", "cool": "idle", "heat_cool": "idle"}.get(mode, "off"),
            )
        elif service == "turn_off":
            s["state"], attrs["brightness"] = "off", None
        elif service == "turn_on":
            s["state"] = "on"
            attrs["brightness"] = round(data.get("brightness_pct", 70) * 255 / 100)

    def start(self) -> None:
        pass

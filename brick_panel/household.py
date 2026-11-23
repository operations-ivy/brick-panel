"""CALENDAR and SHOPPING: Home Assistant's calendars and its shopping list.

Both are open to anyone, as on LCARS: reading the calendar changes nothing,
and ticking off the milk isn't the thermostat, so the panel lock doesn't
apply. A tick is still checked here (from this Pi only, web.py checks that):
only an item that's on the list, only to done or back to needed."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from . import calendar as cal
from .metrics import Metrics

STATUSES = ("needs_action", "completed")


@dataclass
class Household:
    settings: dict
    ha: object  # HomeAssistant or DemoHomeAssistant
    metrics: Metrics

    @property
    def shopping_list(self) -> str:
        return self.settings["shopping"]["entity"]

    def calendar_view(self, now: datetime | None = None) -> dict:
        c = self.settings["calendar"]
        if not c["entities"]:
            return {"available": False, "message": "NO CALENDARS IN THE SETTINGS"}
        events = self.ha.events()
        if events is None:
            message = "CALENDAR UNAVAILABLE" if self.ha.error else "CONNECTING TO THE CALENDAR"
            return {"available": False, "message": message}
        now = now or self.ha.now()
        age = self.ha.events_age()
        stale = age is not None and age > c["stale_seconds"]
        out = cal.view(events, now, c["months"], self.settings["clock"]["hours"])
        self.metrics.set("panel_calendar_events_today", len(out["days"].get(out["today"], [])))
        return {"available": True, "message": "", "stale_minutes": round(age / 60) if stale else None, **out}

    def shopping_view(self) -> dict:
        if not self.shopping_list:
            return {"available": False, "message": "NO SHOPPING LIST IN THE SETTINGS", "items": []}
        items = self.ha.items()
        if items is None:
            message = "SHOPPING LIST UNAVAILABLE" if self.ha.error else "CONNECTING TO THE LIST"
            return {"available": False, "message": message, "items": []}
        rows = [
            {"uid": i["uid"], "summary": (i.get("summary") or "").strip() or "?", "done": i.get("status") == "completed"}
            for i in items
        ]
        rows.sort(key=lambda r: r["done"])  # needed first; stable, so the list's own order within each
        return {
            "available": True,
            "message": "",
            "items": rows,
            "needed": sum(not r["done"] for r in rows),
            "link": self.ha.error or "",
        }

    def tick(self, uid: object, done: object) -> tuple[bool, str]:
        """Tick an item off (done) or back on; (ok, why not)."""
        if not self.shopping_list:
            return False, "no shopping list"
        if not isinstance(done, bool):
            return False, "done must be true or false"
        items = self.ha.items() or []
        if not isinstance(uid, str) or not any(i.get("uid") == uid for i in items):
            return False, "not an item on the list"
        status = STATUSES[done]
        self.ha.call("todo", "update_item", entity_id=self.shopping_list, item=uid, status=status)
        self.ha.set_item_status(uid, status)
        self.metrics.inc("panel_commands_total", action="shopping_item")
        return True, ""

    def view(self) -> dict:
        return {"calendar": self.calendar_view(), "shopping": self.shopping_view()}

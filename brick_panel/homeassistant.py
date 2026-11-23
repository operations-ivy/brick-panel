"""Home Assistant's REST API, from a background thread so a slow or missing
Home Assistant never holds up the page. The panel reads the latest states
(state(), value(), number()), the shopping list's items (items()) and the
calendars' events (events()), and queues service calls (call()); the thread
does the talking, and polls again straight after a call so its result shows.
Adapted from rpi_lcars' datasources/homeassistant.py."""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from collections.abc import Iterable
from datetime import datetime
from datetime import timezone
from typing import Any

from . import calendar as cal
from .metrics import Metrics

log = logging.getLogger(__name__)


class HomeAssistant(threading.Thread):
    def __init__(
        self,
        url: str,
        token: str,
        entities: Iterable[str],
        poll_seconds: float = 5,
        metrics: Metrics | None = None,
        opener: Callable = urllib.request.urlopen,
        clock: Callable[[], float] = time.monotonic,
        todo: str = "",
        todo_seconds: float = 30,
        calendars: Iterable[str] = (),
        calendar_seconds: float = 300,
        calendar_months: int = 2,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        super().__init__(name="homeassistant", daemon=True)
        self.url, self.token = url.rstrip("/"), token
        self.entities = list(dict.fromkeys(e for e in entities if e))
        self.poll_seconds = poll_seconds
        self.metrics, self.opener, self.clock = metrics, opener, clock
        self.todo, self.todo_seconds = todo, todo_seconds
        self.calendars = list(calendars)
        self.calendar_seconds, self.calendar_months = calendar_seconds, calendar_months
        self.now = now or (lambda: datetime.now().astimezone())
        self._states: dict[str, dict] = {}
        self._items: list[dict] | None = None  # the shopping list, once fetched
        self._next_items = 0.0
        self._events: list[dict] | None = None  # every calendar's events, once all have answered
        self._next_events = 0.0
        self.events_updated: float | None = None  # clock() of the last full answer
        self._lock = threading.Lock()
        self._calls: queue.Queue = queue.Queue()
        self._stopping = threading.Event()
        self.connected = False
        self.error = "" if token else "NO TOKEN"
        self.unit = "°F"
        if metrics:
            metrics.set("panel_ha_up", 0)  # down until a poll answers, or for good without a token

    # The panel's side.

    def state(self, entity_id: str) -> dict | None:
        with self._lock:
            return self._states.get(entity_id)

    def attrs(self, entity_id: str) -> dict:
        s = self.state(entity_id)
        return dict(s.get("attributes") or {}) if s else {}

    def value(self, entity_id: str, default: str | None = None) -> str | None:
        s = self.state(entity_id)
        return s["state"] if s and s.get("state") not in (None, "unknown", "unavailable") else default

    def number(self, entity_id: str, default: float) -> float:
        raw = self.value(entity_id)
        if raw is None:
            return default
        try:
            return float(raw)
        except ValueError:
            return default

    def items(self) -> list[dict] | None:
        """The shopping list's items ({"summary", "uid", "status"}), or None
        before the first fetch."""
        with self._lock:
            return None if self._items is None else [dict(i) for i in self._items]

    def set_item_status(self, uid: str, status: str) -> None:
        """Show a change at once, before Home Assistant confirms it."""
        with self._lock:
            for item in self._items or []:
                if item.get("uid") == uid:
                    item["status"] = status

    def events(self) -> list[dict] | None:
        """Every calendar's events (calendar.parse()), or None before they've
        all answered once. Kept while Home Assistant is down."""
        with self._lock:
            return None if self._events is None else list(self._events)

    def events_age(self) -> float | None:
        """Seconds since the calendars last all answered, or None."""
        return None if self.events_updated is None else self.clock() - self.events_updated

    def call(self, domain: str, service: str, **data: object) -> None:
        self._calls.put((domain, service, data))

    def stop(self) -> None:
        self._stopping.set()
        self._calls.put(None)

    # The thread's side.

    def run(self) -> None:
        if not self.token:
            return
        self._fetch_config()
        next_poll = 0.0
        while not self._stopping.is_set():
            if self.clock() >= next_poll:
                self.poll()
                next_poll = self.clock() + self.poll_seconds
            try:
                item = self._calls.get(timeout=max(0.0, next_poll - self.clock()))
            except queue.Empty:
                continue
            if item is None:
                break
            self._call(*item)
            next_poll = 0.0  # show the result now

    def _request(self, method: str, path: str, body: object = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            self.url + path,
            data=data,
            method=method,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        with self.opener(request, timeout=10) as r:
            return json.loads(r.read() or b"null")

    def _count(self, kind: str, result: str) -> None:
        if self.metrics:
            self.metrics.inc("panel_ha_requests_total", kind=kind, result=result)

    def _fetch_config(self) -> None:
        try:
            unit = self._request("GET", "/api/config")["unit_system"]["temperature"]
            self.unit = unit if unit.startswith("°") else f"°{unit}"
        except Exception as e:  # noqa: BLE001 - °F until it answers
            log.warning("config: %s", e)

    def poll(self) -> bool:
        states, ok = {}, True
        for entity in self.entities:
            try:
                states[entity] = self._request("GET", f"/api/states/{entity}")
                self._count("state", "ok")
            except urllib.error.HTTPError as e:
                self._count("state", str(e.code))
                if e.code == 404:  # not there (yet): not a lost link
                    continue
                ok, self.error = False, f"HTTP {e.code}"
                break
            except Exception as e:  # noqa: BLE001 - shown as NO SIGNAL, tried again next poll
                self._count("state", "error")
                ok, self.error = False, "NO SIGNAL"
                log.warning("poll %s: %s", entity, e)
                break
        if ok:
            with self._lock:
                self._states.update(states)
            self.error = ""
            self._fetch_items()
            self._fetch_events()
        self.connected = ok
        if self.metrics:
            self.metrics.set("panel_ha_up", 1 if ok else 0)
        return ok

    def _fetch_items(self) -> None:
        if not self.todo or self.clock() < self._next_items:
            return
        self._next_items = self.clock() + self.todo_seconds
        try:
            answer = self._request("POST", "/api/services/todo/get_items?return_response", {"entity_id": self.todo})
            items = answer["service_response"][self.todo]["items"]
            self._count("items", "ok")
        except Exception as e:  # noqa: BLE001 - the list keeps its last items
            self._count("items", "error")
            log.warning("todo items %s: %s", self.todo, type(e).__name__)
            return
        with self._lock:
            self._items = [i for i in items if isinstance(i, dict) and i.get("uid")]

    def _fetch_events(self) -> None:
        """All the calendars, the month grids from this month's for
        calendar_months months, every calendar_seconds; all or nothing, so one
        calendar failing never hides another's events behind a half answer.
        Titles aren't logged."""
        if not self.calendars or self.clock() < self._next_events:
            return
        self._next_events = self.clock() + self.calendar_seconds
        now = self.now()
        start, end = cal.window(now, self.calendar_months)
        span = {"start": start.astimezone(timezone.utc).isoformat(), "end": end.astimezone(timezone.utc).isoformat()}
        events = []
        for entity in self.calendars:
            try:
                raw = self._request("GET", f"/api/calendars/{entity}?{urllib.parse.urlencode(span)}")
                self._count("calendar", "ok")
            except Exception as e:  # noqa: BLE001 - the calendars keep their last events
                self._count("calendar", "error")
                log.warning("calendar %s: %s", entity, type(e).__name__)
                if self.metrics:
                    self.metrics.set("panel_calendar_up", 0)
                return
            events += [e for e in (cal.parse(r, entity, now.tzinfo) for r in raw or []) if e]
        with self._lock:
            self._events = events
        self.events_updated = self.clock()
        if self.metrics:
            self.metrics.set("panel_calendar_up", 1)

    def _call(self, domain: str, service: str, data: dict) -> None:
        try:
            self._request("POST", f"/api/services/{domain}/{service}", data)
            self._count("call", "ok")
            if domain == "todo":
                self._next_items = 0.0  # fetch the list again with the next poll
        except Exception as e:  # noqa: BLE001 - shown as COMMAND FAILED
            self._count("call", "error")
            self.error = "COMMAND FAILED"
            log.warning("%s.%s %s: %s", domain, service, data, e)

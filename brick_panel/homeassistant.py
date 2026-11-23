"""Home Assistant's REST API, from a background thread so a slow or missing
Home Assistant never holds up the page. The panel reads the latest states
(state(), value(), number()) and queues service calls (call()); the thread
does the talking, and polls again straight after a call so its result shows.
Adapted from rpi_lcars' datasources/homeassistant.py (states and calls only;
the to-do list and calendars come with their screens)."""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from collections.abc import Iterable
from typing import Any

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
    ) -> None:
        super().__init__(name="homeassistant", daemon=True)
        self.url, self.token = url.rstrip("/"), token
        self.entities = list(dict.fromkeys(e for e in entities if e))
        self.poll_seconds = poll_seconds
        self.metrics, self.opener, self.clock = metrics, opener, clock
        self._states: dict[str, dict] = {}
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
        self.connected = ok
        if self.metrics:
            self.metrics.set("panel_ha_up", 1 if ok else 0)
        return ok

    def _call(self, domain: str, service: str, data: dict) -> None:
        try:
            self._request("POST", f"/api/services/{domain}/{service}", data)
            self._count("call", "ok")
        except Exception as e:  # noqa: BLE001 - shown as COMMAND FAILED
            self._count("call", "error")
            self.error = "COMMAND FAILED"
            log.warning("%s.%s %s: %s", domain, service, data, e)

"""JSON from the homelab's own pages, each polled from its own thread so a
slow one never holds up the page: brick9000's board, Prometheus' alerts and
overwatch. A feed keeps its last answer while its source is down; `fresh()`
says whether that answer is still worth showing."""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.request
from collections.abc import Callable

from .metrics import Metrics

log = logging.getLogger(__name__)
USER_AGENT = "brick-panel (github.com/operations-ivy/brick-panel)"


class JsonFeed(threading.Thread):
    def __init__(
        self,
        name: str,
        url: str,
        poll_seconds: float,
        stale_seconds: float,
        metrics: Metrics | None = None,
        opener: Callable = urllib.request.urlopen,
        clock: Callable[[], float] = time.time,
    ) -> None:
        super().__init__(name=f"feed-{name}", daemon=True)
        self.feed, self.url = name, url
        self.poll_seconds, self.stale_seconds = poll_seconds, stale_seconds
        self.metrics, self.opener, self.clock = metrics, opener, clock
        self._stopping = threading.Event()
        self._lock = threading.Lock()
        self._data: object = None
        self.updated: float | None = None  # clock() of the last answer
        self._warned = False
        if metrics:
            metrics.set("panel_feed_up", 0, feed=name)

    @property
    def data(self) -> object:
        with self._lock:
            return self._data

    def age(self) -> float | None:
        return None if self.updated is None else self.clock() - self.updated

    def fresh(self) -> object:
        """The last answer, or None if there's none or it's too old to trust."""
        age = self.age()
        return self.data if age is not None and age <= self.stale_seconds else None

    def poll(self) -> bool:
        request = urllib.request.Request(self.url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
        try:
            with self.opener(request, timeout=20) as response:
                data = json.loads(response.read())
        except Exception as e:  # noqa: BLE001 - shown as offline, tried again next poll
            if not self._warned:  # once, not every poll while it's down
                log.warning("feed %s: %s", self.feed, e)
                self._warned = True
            self._count(up=False)
            return False
        with self._lock:
            self._data = data
        self.updated, self._warned = self.clock(), False
        self._count(up=True)
        return True

    def _count(self, up: bool) -> None:
        if self.metrics:
            self.metrics.set("panel_feed_up", 1 if up else 0, feed=self.feed)
            self.metrics.inc("panel_feed_requests_total", feed=self.feed, result="ok" if up else "error")

    def run(self) -> None:
        while not self._stopping.is_set():
            self.poll()
            self._stopping.wait(self.poll_seconds)

    def stop(self) -> None:
        self._stopping.set()


class DemoFeed:
    """A feed that always has the same answer (--demo)."""

    def __init__(self, data: object) -> None:
        self.data = data
        self.updated = time.time()

    def age(self) -> float:
        return 12.0

    def fresh(self) -> object:
        return self.data

    def start(self) -> None:
        pass


def from_settings(settings: dict, metrics: Metrics) -> dict[str, JsonFeed]:
    """The feeds settings turn on (an empty url turns one off), not started."""
    s = settings["feeds"]
    return {
        name: JsonFeed(name, f["url"], f["poll_seconds"], s["stale_seconds"], metrics)
        for name, f in s["sources"].items()
        if f.get("url")
    }

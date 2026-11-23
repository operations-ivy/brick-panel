"""Night and the backlight: dark overnight, woken (dimmed) by a tap for a
while. The first tap on a dark screen only wakes it, so nothing is pressed by
accident (the page swallows it). The backlight is /sys/class/backlight,
writable by the video group (deploy/90-backlight.rules). Either end of the
night can be "sunset" or "sunrise", from Home Assistant's sun.sun; until Home
Assistant has answered, those are FALLBACK. Adapted from rpi_lcars'
panel/night.py."""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime
from datetime import time as dtime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .metrics import Metrics

log = logging.getLogger(__name__)

SUN_EVENTS = {"sunset": "next_setting", "sunrise": "next_rising"}
FALLBACK = {"sunset": dtime(19, 0), "sunrise": dtime(7, 0)}
Window = tuple[dtime | str, dtime | str]


def parse_window(text: str | None) -> Window | None:
    """ "HH:MM-HH:MM" (may wrap past midnight; either end may be "sunset" or
    "sunrise"), or empty for never."""
    text = (text or "").strip()
    if not text:
        return None
    ends = [t.strip().lower() for t in text.split("-")]
    if len(ends) != 2:
        raise ValueError(f"night window {text!r} isn't START-END")
    start, end = (t if t in SUN_EVENTS else dtime.fromisoformat(t) for t in ends)
    return start, end


def sun_times(attrs: dict) -> dict[str, dtime]:
    """{"sunset": time, "sunrise": time} (local) from sun.sun's attributes;
    either is missing when Home Assistant hasn't said."""
    out = {}
    for name, attr in SUN_EVENTS.items():
        # Missing or unreadable: left out, so in_window() uses FALLBACK.
        with contextlib.suppress(KeyError, TypeError, ValueError):
            out[name] = datetime.fromisoformat(attrs[attr]).astimezone().time().replace(second=0, microsecond=0)
    return out


def in_window(window: Window | None, at: datetime, sun: dict[str, dtime] | None = None) -> bool:
    if window is None:
        return False
    sun = sun or {}
    start, end = (sun.get(t, FALLBACK[t]) if isinstance(t, str) else t for t in window)
    t = at.time()
    return start <= t < end if start <= end else t >= start or t < end


class Backlight:
    def __init__(self, root: str | Path = "/sys/class/backlight") -> None:
        devices = sorted(Path(root).glob("*/brightness"))
        self.path: Path | None = devices[0] if devices else None
        self.max = int((self.path.parent / "max_brightness").read_text()) if self.path else 0
        self.level: int | None = None

    def set(self, fraction: float) -> None:
        """0 is off; anything else is at least the lowest lit level."""
        level = 0 if fraction <= 0 else max(1, round(self.max * fraction))
        if self.path is None or level == self.level:
            return
        try:
            self.path.write_text(str(level))
            self.level = level
        except OSError as e:
            # Once is enough: stop trying rather than warn every second.
            log.warning("backlight %s not writable, leaving it alone: %s", self.path, e)
            self.path = None


class Night:
    def __init__(
        self,
        window: str | None,
        night_level: float,
        day_level: float,
        wake_seconds: float,
        backlight: Backlight | None = None,
        metrics: Metrics | None = None,
        now: Callable[[], datetime] = datetime.now,
        clock: Callable[[], float] = time.monotonic,
        sun: Callable[[], dict[str, dtime]] | None = None,
    ) -> None:
        self.window = parse_window(window)
        self.night_level, self.day_level = night_level, day_level
        self.wake_seconds = wake_seconds
        self.backlight, self.metrics = backlight, metrics
        self.now, self.clock = now, clock
        self.sun = sun or (lambda: {})  # () -> sun_times(...): Home Assistant's sunset and sunrise
        self._awake_until = 0.0
        self._stopping = threading.Event()

    @classmethod
    def from_settings(cls, settings: dict, backlight: Backlight | None, metrics: Metrics, sun) -> Night:
        n = settings["night"]
        return cls(n["window"], n["level"], n["day_level"], n["wake_seconds"], backlight, metrics, sun=sun)

    @property
    def is_night(self) -> bool:
        return in_window(self.window, self.now(), self.sun())

    @property
    def dark(self) -> bool:
        return self.is_night and self.clock() >= self._awake_until

    @property
    def level(self) -> float:
        if not self.is_night:
            return self.day_level
        return 0.0 if self.dark else self.night_level

    def tap(self) -> bool:
        """A touch. True when it only woke the screen (the page swallows it)."""
        was_dark = self.dark
        if self.is_night:
            self._awake_until = self.clock() + self.wake_seconds
        if self.metrics:
            self.metrics.inc("panel_taps_total", woke=str(was_dark).lower())
        self.apply()
        return was_dark

    def view(self) -> dict:
        is_night = self.is_night
        awake = max(0.0, self._awake_until - self.clock()) if is_night else 0.0
        return {
            "is_night": is_night,
            "dark": is_night and awake == 0,
            "awake_for": round(awake, 1),
            "wake_seconds": self.wake_seconds,
        }

    def apply(self) -> None:
        level = self.level
        if self.backlight is not None:
            self.backlight.set(level)
        if self.metrics:
            self.metrics.set("panel_backlight_level", level)

    # The thread that keeps the backlight in step (dark when a wake runs out).

    def run(self) -> None:
        while not self._stopping.is_set():
            self.apply()
            self._stopping.wait(1)

    def start(self) -> None:
        threading.Thread(target=self.run, name="night", daemon=True).start()

    def stop(self) -> None:
        self._stopping.set()

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
    """When the screen is on (the user, 2026-11-23):

    - A double tap always sleeps the screen, or wakes it.
    - Night (window, 18:00-07:00): asleep unless woken by a double tap; a
      single tap doesn't wake it. Woken, it sleeps again idle_seconds after
      the last touch, or on a double tap.
    - Woken in the dim window (22:00-07:00): the backlight at level, not
      day_level.
    - Day: on at day_level; a double tap sleeps it until a double tap wakes
      it, or the morning (the night's end) does.
    """

    def __init__(
        self,
        window: str | None,
        level: float,
        day_level: float,
        idle_seconds: float,
        backlight: Backlight | None = None,
        metrics: Metrics | None = None,
        now: Callable[[], datetime] = datetime.now,
        clock: Callable[[], float] = time.monotonic,
        sun: Callable[[], dict[str, dtime]] | None = None,
        dim: str | None = None,
    ) -> None:
        self.window = parse_window(window)
        self.dim = parse_window(dim)
        self.dim_level, self.day_level = level, day_level
        self.idle_seconds = idle_seconds
        self.backlight, self.metrics = backlight, metrics
        self.now, self.clock = now, clock
        self.sun = sun or (lambda: {})  # () -> sun_times(...): Home Assistant's sunset and sunrise
        self._awake_until = 0.0  # night: awake until then
        self._asleep = False  # day: put to sleep by a double tap
        self._was_night: bool | None = None
        self._lock = threading.Lock()
        self._stopping = threading.Event()

    @classmethod
    def from_settings(cls, settings: dict, backlight: Backlight | None, metrics: Metrics, sun) -> Night:
        n = settings["night"]
        return cls(
            n["window"], n["level"], n["day_level"], n["idle_seconds"], backlight, metrics, sun=sun, dim=n["dim"]
        )

    @property
    def is_night(self) -> bool:
        return in_window(self.window, self.now(), self.sun())

    def _turn(self) -> bool:
        """is_night, starting each night asleep and each day awake."""
        night = self.is_night
        if night != self._was_night:
            self._awake_until, self._asleep, self._was_night = 0.0, False, night
        return night

    @property
    def dark(self) -> bool:
        with self._lock:
            if self._turn():
                return self.clock() >= self._awake_until
            return self._asleep

    @property
    def level(self) -> float:
        if self.dark:
            return 0.0
        return self.dim_level if in_window(self.dim, self.now(), self.sun()) else self.day_level

    def double_tap(self) -> bool:
        """Sleep the screen, or wake it. True when it's awake now."""
        with self._lock:
            if self._turn():
                waking = self.clock() >= self._awake_until
                self._awake_until = self.clock() + self.idle_seconds if waking else 0.0
            else:
                waking = self._asleep
                self._asleep = not waking
        if self.metrics:
            self.metrics.inc("panel_double_taps_total", woke=str(waking).lower())
        self.apply()
        return waking

    def touch(self) -> None:
        """A touch on the awake screen: at night, the idle time starts again."""
        with self._lock:
            if self._turn() and self.clock() < self._awake_until:
                self._awake_until = self.clock() + self.idle_seconds

    def view(self) -> dict:
        dark = self.dark
        with self._lock:
            awake = max(0.0, self._awake_until - self.clock()) if self._was_night else None
        return {
            "is_night": bool(self._was_night),
            "dark": dark,
            "awake_for": None if awake is None else round(awake, 1),  # night: seconds until it sleeps
            "idle_seconds": self.idle_seconds,
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

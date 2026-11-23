"""Real user monitoring: how the panel's page is doing on the wall, between
bench runs. The page (static/rum.js) posts a report every 30 s: its taps'
time to the next frame, long tasks, a sample of frames while nothing's
changing, errors, its memory, how long it's been up, and how long the state
polls took. This turns a report into Prometheus metrics (and errors into the
log, which reaches Loki). Only from the panel itself: web.py checks that."""

from __future__ import annotations

import logging

from .metrics import Metrics
from .perf import clean

log = logging.getLogger(__name__)

FAST_TAP_MS, OK_TAP_MS = 100, 200  # the web's usual thresholds for a response
MAX_ERRORS_LOGGED = 5  # per report, so a loop of errors can't flood the log


def _numbers(value: object, limit: int = 2000) -> list[float]:
    """The numbers in a list from the page (perf.clean() drops the rest)."""
    return clean(value[:limit]) if isinstance(value, list) else []


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        return None
    return float(value)


def tap_speed(ms: float) -> str:
    if ms < FAST_TAP_MS:
        return "fast"
    return "ok" if ms < OK_TAP_MS else "slow"


def record(metrics: Metrics, body: dict[str, object], late_after_ms: float, screens: list[str]) -> None:
    """One report from the page."""
    taps = _numbers(body.get("taps"))
    for ms in taps:
        metrics.inc("panel_rum_taps_total", speed=tap_speed(ms))
    if taps:
        metrics.set("panel_rum_tap_worst_seconds", max(taps) / 1000)

    long_tasks = _numbers(body.get("long_tasks"))
    if long_tasks:
        metrics.inc("panel_rum_long_tasks_total", len(long_tasks))
        metrics.inc("panel_rum_long_task_seconds_total", sum(long_tasks) / 1000)

    idle = body.get("idle")
    if isinstance(idle, dict) and idle.get("screen") in screens:
        frames = _numbers(idle.get("frames"))
        late = sum(f > late_after_ms for f in frames)
        screen = idle["screen"]
        metrics.inc("panel_rum_idle_frames_total", len(frames) - late, screen=screen, result="on_time")
        metrics.inc("panel_rum_idle_frames_total", late, screen=screen, result="late")

    polls = _numbers(body.get("polls"))
    if polls:
        metrics.inc("panel_rum_polls_total", len(polls))
        metrics.inc("panel_rum_poll_seconds_total", sum(polls) / 1000)

    errors = body.get("errors")
    if isinstance(errors, list) and errors:
        metrics.inc("panel_rum_errors_total", len(errors))
        for e in errors[:MAX_ERRORS_LOGGED]:
            if isinstance(e, dict):
                log.warning(
                    "page error: %s (%s:%s)", str(e.get("message"))[:300], str(e.get("source"))[-60:], e.get("line")
                )

    for key, name in (("heap_bytes", "panel_rum_heap_bytes"), ("uptime_s", "panel_rum_page_uptime_seconds")):
        if (value := _number(body.get(key))) is not None:
            metrics.set(name, value)
    if body.get("loaded") is True:
        metrics.inc("panel_rum_page_loads_total")

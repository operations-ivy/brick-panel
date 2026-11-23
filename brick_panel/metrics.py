"""Prometheus metrics: counters and gauges with labels, rendered in the text
format. The web server (web.py) serves them at /metrics."""

from __future__ import annotations

import threading

HELP = {
    "panel_info": ("gauge", "Always 1; the version running, as a label."),
    "panel_weather_up": ("gauge", "1 while a weather source answers."),
    "panel_weather_source": ("gauge", "1 for the weather source the data shown came from, by source."),
    "panel_weather_requests_total": ("counter", "Requests to weather services, by source, kind and result."),
    "panel_weather_alerts": (
        "gauge",
        "Active weather alerts (-1: unknown, the National Weather Service didn't answer).",
    ),
    "panel_weather_last_update_timestamp_seconds": ("gauge", "When the weather shown was fetched."),
    "panel_weather_temperature_fahrenheit": ("gauge", "Outside temperature, from the weather source."),
    "panel_feed_up": ("gauge", "1 while a homelab feed (board, prometheus, overwatch) answers, by feed."),
    "panel_feed_requests_total": ("counter", "Requests to the homelab's feeds, by feed and result."),
    "panel_ha_up": ("gauge", "1 while Home Assistant answers."),
    "panel_ha_requests_total": ("counter", "Requests to Home Assistant, by kind and result."),
    "panel_commands_total": ("counter", "Commands sent to Home Assistant, by action."),
    "panel_unlock_attempts_total": ("counter", "Codes tried on the keypad, by result."),
    "panel_relocks_total": ("counter", "The panel lock closing, by reason (idle, button, dark)."),
    "panel_calendar_up": ("gauge", "1 while every calendar answers."),
    "panel_calendar_events_today": ("gauge", "Events on the calendars today."),
    "panel_backlight_level": ("gauge", "The backlight, 0 (off) to 1 (full)."),
    "panel_taps_total": ("counter", "Taps at night, by woke (true: the tap only woke the screen)."),
    "panel_rum_taps_total": (
        "counter",
        "Taps on the page, by speed to the next frame (fast <100 ms, ok <200 ms, slow).",
    ),
    "panel_rum_tap_worst_seconds": ("gauge", "The slowest tap in the page's last report."),
    "panel_rum_long_tasks_total": ("counter", "Page tasks over 50 ms (the page couldn't draw meanwhile)."),
    "panel_rum_long_task_seconds_total": ("counter", "Time spent in the page's long tasks."),
    "panel_rum_idle_frames_total": (
        "counter",
        "Frames sampled while no screen changes, by screen and result (on_time, late).",
    ),
    "panel_rum_polls_total": ("counter", "The page's state polls."),
    "panel_rum_poll_seconds_total": ("counter", "Time the page's state polls took."),
    "panel_rum_errors_total": ("counter", "Errors in the page (each is logged)."),
    "panel_rum_heap_bytes": ("gauge", "The page's JavaScript memory."),
    "panel_rum_page_uptime_seconds": ("gauge", "Seconds since the page last loaded."),
    "panel_rum_page_loads_total": ("counter", "Page loads (each server start reloads it)."),
    "panel_room_sensor_up": ("gauge", "1 while the room sensor reads."),
    "panel_room_reads_total": ("counter", "Room sensor reads, by result."),
    "panel_room_temperature_fahrenheit": ("gauge", "The room's temperature, offset applied."),
    "panel_room_humidity_percent": ("gauge", "The room's relative humidity."),
    "panel_page_seen_timestamp_seconds": ("gauge", "When the kiosk's page last asked for its state."),
    "panel_screen": ("gauge", "1 for the screen being shown, by screen."),
    "panel_transitions_total": ("counter", "Screen changes, by result: smooth (no frame late) or janky."),
    "panel_transition_frames_total": ("counter", "Frames drawn during screen changes, by result (on_time, late)."),
    "panel_transition_worst_frame_seconds": ("gauge", "The longest frame of the last screen change."),
    "panel_bench_p95_frame_seconds": ("gauge", "The 95th percentile frame of the last bench run."),
    "panel_bench_late_ratio": ("gauge", "The share of late frames in the last bench run."),
    "panel_bench_timestamp_seconds": ("gauge", "When the last bench run finished."),
}

# Label values that exist from the start, so a counter reads 0, not "no data".
KNOWN = {
    "panel_transitions_total": ("result", ("smooth", "janky")),
    "panel_transition_frames_total": ("result", ("on_time", "late")),
    "panel_unlock_attempts_total": ("result", ("granted", "denied", "locked_out", "hard_locked", "no_code")),
    "panel_relocks_total": ("reason", ("idle", "button", "dark")),
    "panel_rum_taps_total": ("speed", ("fast", "ok", "slow")),
}


Labels = tuple[tuple[str, str], ...]


def _escape(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _labels(labels: Labels) -> str:
    if not labels:
        return ""
    return "{" + ",".join(f'{k}="{_escape(v)}"' for k, v in labels) + "}"


class Metrics:
    def __init__(self) -> None:
        self._values: dict[tuple[str, tuple], float] = {}
        self._lock = threading.Lock()
        for name, (label, values) in KNOWN.items():
            for value in values:
                self._values[(name, ((label, value),))] = 0

    @staticmethod
    def _key(name: str, labels: dict) -> tuple[str, tuple]:
        return name, tuple(sorted(labels.items()))

    def inc(self, name: str, amount: float = 1, **labels: str) -> None:
        key = self._key(name, labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0) + amount

    def set(self, name: str, value: float, **labels: str) -> None:
        with self._lock:
            self._values[self._key(name, labels)] = value

    def get(self, name: str, **labels: str) -> float:
        with self._lock:
            return self._values.get(self._key(name, labels), 0)

    def render(self) -> str:
        with self._lock:
            items = sorted(self._values.items())
        out, seen = [], set()
        for (name, labels), value in items:
            if name not in seen:
                kind, text = HELP.get(name, ("untyped", name))
                out += [f"# HELP {name} {text}", f"# TYPE {name} {kind}"]
                seen.add(name)
            out.append(f"{name}{_labels(labels)} {value:g}")
        return "\n".join(out) + "\n"

from __future__ import annotations

from datetime import datetime
from datetime import time

import pytest

from brick_panel.metrics import Metrics
from brick_panel.night import Backlight
from brick_panel.night import in_window
from brick_panel.night import Night
from brick_panel.night import parse_window
from brick_panel.night import sun_times


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def at(hour, minute=0):
    return datetime(2026, 11, 22, hour, minute)


def test_parse_window():
    assert parse_window("") is None and parse_window(None) is None
    assert parse_window("21:00-07:00") == (time(21), time(7))
    assert parse_window("Sunset - sunrise") == ("sunset", "sunrise")
    with pytest.raises(ValueError):
        parse_window("21:00")


def test_in_window_wraps_midnight_and_follows_the_sun():
    w = parse_window("21:00-07:00")
    assert in_window(w, at(23)) and in_window(w, at(3)) and not in_window(w, at(12))
    assert in_window(parse_window("01:00-05:00"), at(2)) and not in_window(parse_window("01:00-05:00"), at(6))
    sun = parse_window("sunset-sunrise")
    assert in_window(sun, at(19, 30))  # the fallback sunset is 19:00
    assert not in_window(sun, at(19, 30), {"sunset": time(20), "sunrise": time(6)})
    assert not in_window(None, at(23))


def test_sun_times():
    attrs = {"next_setting": "2026-11-22T21:45:00+00:00", "next_rising": "nonsense"}
    times = sun_times(attrs)
    assert set(times) == {"sunset"} and times["sunset"].second == 0


def test_a_tap_wakes_the_dark_screen_dimmed_for_a_while(tmp_path):
    clock, metrics = Clock(), Metrics()
    dev = tmp_path / "panel"
    dev.mkdir()
    (dev / "brightness").write_text("255")
    (dev / "max_brightness").write_text("255")
    night = Night("21:00-07:00", 0.08, 1.0, 60, Backlight(tmp_path), metrics, now=lambda: at(23), clock=clock)
    night.apply()
    assert night.dark and (dev / "brightness").read_text() == "0"
    assert night.view() == {"is_night": True, "dark": True, "awake_for": 0.0, "wake_seconds": 60}
    assert night.tap() is True  # only woke it
    assert (dev / "brightness").read_text() == "20"  # 8% of 255
    assert night.tap() is False  # awake: a real tap
    assert night.view()["awake_for"] == 60
    clock.t += 61
    night.apply()
    assert night.dark and (dev / "brightness").read_text() == "0"
    assert metrics.get("panel_taps_total", woke="true") == 1
    assert metrics.get("panel_backlight_level") == 0


def test_by_day_taps_do_nothing_special():
    night = Night("21:00-07:00", 0.08, 1.0, 60, now=lambda: at(12))
    assert night.tap() is False and night.level == 1.0 and not night.dark
    assert night.view()["is_night"] is False


def test_an_unwritable_backlight_is_left_alone(tmp_path):
    dev = tmp_path / "panel"
    dev.mkdir()
    (dev / "brightness").mkdir()  # writing to it fails
    (dev / "max_brightness").write_text("100")
    light = Backlight(tmp_path)
    light.set(0.5)
    assert light.path is None
    assert Backlight(tmp_path / "none").path is None

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


class Now:
    def __init__(self, hour, minute=0):
        self.t = at(hour, minute)

    def __call__(self):
        return self.t


def rules(now, clock=None, backlight=None, metrics=None):
    """The user's rules (2026-11-23): asleep 18:00-07:00 unless woken, dim
    after 22:00, 5 minutes idle."""
    return Night("18:00-07:00", 0.6, 1.0, 300, backlight, metrics, now=now, clock=clock or Clock(), dim="22:00-07:00")


def test_at_night_only_a_double_tap_wakes_it_and_it_sleeps_when_idle(tmp_path):
    clock, metrics = Clock(), Metrics()
    dev = tmp_path / "panel"
    dev.mkdir()
    (dev / "brightness").write_text("255")
    (dev / "max_brightness").write_text("255")
    night = rules(Now(19), clock, Backlight(tmp_path), metrics)
    night.apply()
    assert night.dark
    assert (dev / "brightness").read_text() == "0"
    assert night.view() == {"is_night": True, "dark": True, "awake_for": 0.0, "idle_seconds": 300}
    night.touch()  # a single touch doesn't wake it
    assert night.dark
    assert night.double_tap() is True
    assert not night.dark
    assert (dev / "brightness").read_text() == "255"  # before 22:00: full
    clock.t += 200
    night.touch()  # in use: the 5 minutes start again
    clock.t += 200
    assert not night.dark
    clock.t += 101
    night.apply()
    assert night.dark
    assert metrics.get("panel_double_taps_total", woke="true") == 1


def test_a_double_tap_sleeps_it_at_night():
    night = rules(Now(20))
    night.double_tap()
    assert night.double_tap() is False
    assert night.dark


def test_woken_after_ten_it_is_dimmed():
    night = rules(Now(23, 30))
    night.double_tap()
    assert night.level == 0.6


def test_by_day_it_stays_on_until_a_double_tap():
    clock = Clock()
    night = rules(Now(12), clock)
    assert not night.dark
    assert night.level == 1.0
    clock.t += 3600
    assert not night.dark  # no idle sleep by day
    assert night.view()["awake_for"] is None
    assert night.double_tap() is False
    assert night.dark
    assert night.level == 0.0
    assert night.double_tap() is True
    assert not night.dark


def test_each_night_starts_asleep_and_each_morning_awake():
    now = Now(17, 59)
    night = rules(now)
    night.double_tap()  # put to sleep by day
    assert night.dark
    now.t = at(18, 0)
    assert night.dark  # night: asleep anyway
    night.double_tap()
    assert not night.dark
    now.t = datetime(2026, 11, 23, 7, 0)
    assert not night.dark  # 07:00: on, and stays on
    now.t = datetime(2026, 11, 23, 18, 0)
    assert night.dark  # the next evening starts asleep, not awake from last night


def test_an_unwritable_backlight_is_left_alone(tmp_path):
    dev = tmp_path / "panel"
    dev.mkdir()
    (dev / "brightness").mkdir()  # writing to it fails
    (dev / "max_brightness").write_text("100")
    light = Backlight(tmp_path)
    light.set(0.5)
    assert light.path is None
    assert Backlight(tmp_path / "none").path is None

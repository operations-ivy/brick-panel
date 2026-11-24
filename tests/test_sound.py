from __future__ import annotations

from datetime import datetime

import yaml

from brick_panel.sound import EVENTS
from brick_panel.sound import Sound

DEFAULTS = {"level": "medium", "quiet_hours": "22:00-07:00", "events": {"tap": True, "alert": True}}


def test_defaults_until_something_is_ticked(tmp_path):
    view = Sound(DEFAULTS, tmp_path / "sound.yaml").view(datetime(2026, 11, 23, 12, 0))
    assert set(view["events"]) == set(EVENTS) and all(view["events"].values())
    assert view["level"] == "medium" and view["gain"] == 1.0
    assert not view["quiet"] and view["quiet_window"] == "22:00-07:00"
    assert not view["quiet_sound"] and not view["quiet_alerts"]


def test_quiet_hours_wrap_past_midnight(tmp_path):
    s = Sound(DEFAULTS, tmp_path / "sound.yaml")
    assert s.quiet(datetime(2026, 11, 23, 23, 30))
    assert s.quiet(datetime(2026, 11, 24, 6, 59))
    assert not s.quiet(datetime(2026, 11, 24, 7, 0))
    assert not Sound({**DEFAULTS, "quiet_hours": ""}, tmp_path / "x.yaml").quiet(datetime(2026, 11, 23, 23, 30))


def test_changes_are_saved_and_survive_a_restart(tmp_path):
    path = tmp_path / "conf" / "sound.yaml"
    s = Sound(DEFAULTS, path)
    assert s.change({"event": "tap", "on": False}) == (True, "")
    assert s.change({"level": "low"}) == (True, "")
    assert s.change({"switch": "quiet_alerts", "on": True}) == (True, "")
    saved = yaml.safe_load(path.read_text())
    assert saved["events"]["tap"] is False and saved["level"] == "low" and saved["quiet_alerts"] is True
    again = Sound(DEFAULTS, path).view()
    assert again["events"]["tap"] is False and again["events"]["alert"] is True
    assert again["level"] == "low" and again["gain"] == 0.74 and again["quiet_alerts"] is True


def test_bad_changes_are_refused_and_change_nothing(tmp_path):
    path = tmp_path / "sound.yaml"
    s = Sound(DEFAULTS, path)
    for body in (
        {"event": "kazoo", "on": True},
        {"event": "tap", "on": "yes"},
        {"level": "eleven"},
        {"switch": "quiet_everything", "on": True},
        {},
    ):
        ok, why = s.change(body)
        assert not ok and why
    assert not path.exists()


def test_a_broken_or_odd_file_falls_back_to_the_defaults(tmp_path):
    path = tmp_path / "sound.yaml"
    path.write_text("events: [not, a, mapping\n")
    assert Sound(DEFAULTS, path).view()["events"]["tap"] is True
    path.write_text(yaml.safe_dump({"events": {"tap": "off", "kazoo": False}, "level": "eleven", "quiet_sound": 1}))
    view = Sound(DEFAULTS, path).view()
    assert view["events"]["tap"] is True and "kazoo" not in view["events"]
    assert view["level"] == "medium" and view["quiet_sound"] is False

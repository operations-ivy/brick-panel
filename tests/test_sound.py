from __future__ import annotations

from datetime import datetime
from datetime import time as dtime

import pytest
import yaml

from brick_panel import sound as sound_mod
from brick_panel.sound import EVENTS
from brick_panel.sound import Sound

DEFAULTS = {"level": "medium", "quiet_hours": "22:00-07:00", "events": {"tap": True, "alert": True}}


def test_defaults_until_something_is_ticked(tmp_path):
    view = Sound(DEFAULTS, tmp_path / "sound.yaml").view(datetime(2026, 11, 23, 12, 0))
    assert set(view["events"]) == set(EVENTS)
    assert all(view["events"].values())
    assert view["level"] == "medium"
    assert view["gain"] == 1.0
    assert not view["quiet"]
    assert view["quiet_window"] == "22:00-07:00"
    assert not view["muted"]


def test_from_settings_reads_the_sound_section(tmp_path):
    settings = {"sound": {**DEFAULTS, "file": str(tmp_path / "sound.yaml"), "level": "low"}}
    s = Sound.from_settings(settings)
    assert s.path == tmp_path / "sound.yaml"
    assert s.view()["level"] == "low"


def test_quiet_hours_wrap_past_midnight(tmp_path):
    s = Sound(DEFAULTS, tmp_path / "sound.yaml")
    assert s.quiet(datetime(2026, 11, 23, 23, 30))
    assert s.quiet(datetime(2026, 11, 24, 6, 59))
    assert not s.quiet(datetime(2026, 11, 24, 7, 0))


def test_no_quiet_hours(tmp_path):
    assert not Sound({**DEFAULTS, "quiet_hours": ""}, tmp_path / "sound.yaml").quiet(datetime(2026, 11, 23, 23, 30))


def test_quiet_hours_can_follow_the_sun(tmp_path):
    sun = {"sunset": dtime(17, 5), "sunrise": dtime(7, 10)}
    s = Sound({**DEFAULTS, "quiet_hours": "sunset-sunrise"}, tmp_path / "sound.yaml", sun=lambda: sun)
    assert s.quiet(datetime(2026, 11, 23, 17, 30))
    assert not s.quiet(datetime(2026, 11, 23, 16, 59))


def test_changes_are_saved_and_survive_a_restart(tmp_path):
    path = tmp_path / "conf" / "sound.yaml"
    s = Sound(DEFAULTS, path)
    assert s.change({"event": "tap", "on": False}) == (True, "")
    assert s.change({"level": "low"}) == (True, "")
    saved = yaml.safe_load(path.read_text())
    assert saved["events"]["tap"] is False
    assert saved["level"] == "low"
    again = Sound(DEFAULTS, path).view()
    assert again["events"]["tap"] is False
    assert again["events"]["alert"] is True
    assert again["level"] == "low"
    assert again["gain"] == 0.74


@pytest.mark.parametrize(
    "body",
    [
        {"event": "kazoo", "on": True},
        {"event": "tap", "on": "yes"},
        {"level": "eleven"},
        {},
    ],
)
def test_bad_changes_are_refused_and_change_nothing(tmp_path, body):
    path = tmp_path / "sound.yaml"
    ok, why = Sound(DEFAULTS, path).change(body)
    assert not ok
    assert why
    assert not path.exists()


def test_a_failed_save_is_reported(tmp_path, monkeypatch):
    s = Sound(DEFAULTS, tmp_path / "sound.yaml")

    def full_disk(self):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(sound_mod.Sound, "_save", full_disk)
    assert s.change({"level": "low"}) == (False, "couldn't save")


def test_an_unreadable_file_falls_back_to_the_defaults(tmp_path):
    path = tmp_path / "sound.yaml"
    path.write_text("events: [not, a, mapping\n")
    assert Sound(DEFAULTS, path).view()["events"]["tap"] is True


def test_odd_saved_values_are_ignored(tmp_path):
    path = tmp_path / "sound.yaml"
    path.write_text(yaml.safe_dump({"events": {"tap": "off", "kazoo": False}, "level": "eleven", "quiet_alerts": True}))
    view = Sound(DEFAULTS, path).view()
    assert view["events"]["tap"] is True
    assert "kazoo" not in view["events"]
    assert view["level"] == "medium"
    assert "quiet_alerts" not in view  # from before the mute button


def test_an_empty_events_section_is_all_on(tmp_path):
    assert all(Sound({**DEFAULTS, "events": None}, tmp_path / "sound.yaml").view()["events"].values())


QUIET = {**DEFAULTS, "quiet_hours": "18:00-08:00"}


def test_muted_in_quiet_hours(tmp_path):
    s = Sound(QUIET, tmp_path / "sound.yaml")
    assert s.muted(datetime(2026, 11, 23, 18, 0))
    assert s.muted(datetime(2026, 11, 24, 7, 59))
    assert not s.muted(datetime(2026, 11, 24, 8, 0))


def test_unmuted_in_the_evening_until_eight(tmp_path):
    s = Sound(QUIET, tmp_path / "sound.yaml")
    evening = datetime(2026, 11, 23, 21, 0)
    assert s.toggle(evening) is False
    assert not s.muted(datetime(2026, 11, 24, 7, 59))
    assert not s.muted(datetime(2026, 11, 24, 12, 0))  # day: sound anyway
    assert s.muted(datetime(2026, 11, 24, 18, 0))  # the next evening: muted again


def test_muted_by_day_until_six(tmp_path):
    s = Sound(QUIET, tmp_path / "sound.yaml")
    assert s.toggle(datetime(2026, 11, 23, 9, 0)) is True
    assert s.muted(datetime(2026, 11, 23, 17, 59))
    assert s.muted(datetime(2026, 11, 23, 18, 0))  # quiet hours: muted anyway
    assert not s.muted(datetime(2026, 11, 24, 8, 0))  # the next morning: sound again


def test_the_button_flips_back(tmp_path):
    s = Sound(QUIET, tmp_path / "sound.yaml")
    at = datetime(2026, 11, 23, 21, 0)
    s.toggle(at)
    assert s.toggle(at) is True
    assert s.muted(at)


def test_without_quiet_hours_the_button_holds(tmp_path):
    s = Sound({**DEFAULTS, "quiet_hours": ""}, tmp_path / "sound.yaml")
    assert s.toggle(datetime(2026, 11, 23, 12, 0)) is True
    assert s.muted(datetime(2027, 1, 1, 12, 0))


def test_unmuted_after_sunset_until_sunrise(tmp_path):
    sun = {"sunset": dtime(17, 5), "sunrise": dtime(7, 10)}
    s = Sound({**DEFAULTS, "quiet_hours": "sunset-sunrise"}, tmp_path / "sound.yaml", sun=lambda: sun)
    assert s.toggle(datetime(2026, 11, 23, 20, 0)) is False
    assert not s.muted(datetime(2026, 11, 24, 7, 9))
    assert s.muted(datetime(2026, 11, 24, 17, 5))

from __future__ import annotations

import yaml

from brick_panel.guest import Guest
from brick_panel.metrics import Metrics


def test_from_the_defaults_it_is_office_mode(settings, tmp_path):
    settings["guest"]["file"] = str(tmp_path / "guest.yaml")
    g = Guest.from_settings(settings)
    assert g() is False and g.view() == {"on": False}


def test_a_switch_is_saved_and_survives_a_restart(tmp_path):
    path, metrics = tmp_path / "guest.yaml", Metrics()
    g = Guest(False, path, metrics)
    assert g.change({"on": True}) == (True, "")
    assert g() is True
    assert yaml.safe_load(path.read_text()) == {"active": True}
    assert "panel_guest_mode 1" in metrics.render()
    assert Guest(False, path)() is True


def test_a_bad_switch_changes_nothing(tmp_path):
    g = Guest(False, tmp_path / "guest.yaml")
    assert g.change({"on": "yes"})[0] is False
    assert g() is False and not (tmp_path / "guest.yaml").exists()


def test_a_failed_save_changes_nothing(tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")
    g = Guest(False, blocker / "guest.yaml")
    assert g.change({"on": True}) == (False, "couldn't save")
    assert g() is False


def test_an_unreadable_file_falls_back_to_the_default(tmp_path):
    path = tmp_path / "guest.yaml"
    path.write_text("active: [unclosed")
    assert Guest(True, path)() is True

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from brick_panel import settings as S


def test_defaults_have_the_plus_and_portrait():
    s = S.load()
    assert s["plus"] == {"up": "weather", "right": "climate", "down": "lights", "left": "brick"}
    assert s["billboards"] == ["alerts", "calendar", "shopping"]
    assert s["kiosk"]["rotation"] == 90
    assert s["server"]["port"] == 8767
    assert s["weather"]["point"] == ""  # the panel's location is never in git


def test_local_file_merges_key_by_key(tmp_path):
    local = tmp_path / "settings.yaml"
    local.write_text("kiosk:\n  rotation: 270\nweather:\n  point: '1.5,2.5'\n")
    s = S.load(local)
    assert s["kiosk"] == {"output": "DSI-1", "rotation": 270}
    assert s["weather"]["point"] == "1.5,2.5"
    assert s["weather"]["poll_seconds"] == 300


def test_empty_local_file_is_fine(tmp_path):
    local = tmp_path / "settings.yaml"
    local.write_text("# nothing yet\n")
    assert S.load(local) == S.load()


def test_merge_leaves_base_alone():
    base = {"a": {"b": 1, "c": 2}}
    assert S.merge(base, {"a": {"b": 9}}) == {"a": {"b": 9, "c": 2}}
    assert base == {"a": {"b": 1, "c": 2}}


def test_cli_prints_one_value(tmp_path):
    local = tmp_path / "settings.yaml"
    local.write_text("deploy:\n  branch: try-this\n")
    out = subprocess.run(
        [sys.executable, "-m", "brick_panel.settings", "deploy.branch"],
        capture_output=True,
        text=True,
        check=True,
        cwd=Path(__file__).parents[1],
        env={**os.environ, "BRICK_PANEL_SETTINGS": str(local)},
    )
    assert out.stdout.strip() == "try-this"


def test_cli_refuses_an_unknown_setting(capsys):
    assert S.main(["settings", "kiosk.rotaton"]) == 1
    assert "no such setting" in capsys.readouterr().err
    assert S.main(["settings"]) == 2


def test_local_file_must_be_a_mapping(tmp_path):
    local = tmp_path / "settings.yaml"
    local.write_text("- a list\n")
    with pytest.raises(ValueError, match="mapping"):
        S.load(local)

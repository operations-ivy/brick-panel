"""Settings: defaults.yaml beside this file, with the panel's own
~/.config/brick-panel/settings.yaml (or $BRICK_PANEL_SETTINGS) merged over it.

    python3 -m brick_panel.settings kiosk.rotation    # prints one value
"""

from __future__ import annotations

import copy
import os
import sys
from pathlib import Path

import yaml

DEFAULTS = Path(__file__).with_name("defaults.yaml")
LOCAL = Path("~/.config/brick-panel/settings.yaml")


def merge(base: dict, over: dict) -> dict:
    """base with over's keys laid on top, dicts merged key by key."""
    out = copy.deepcopy(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], value)
        else:
            out[key] = value
    return out


def local_path() -> Path:
    return Path(os.environ.get("BRICK_PANEL_SETTINGS") or LOCAL).expanduser()


def load(path: Path | None = None) -> dict:
    settings = yaml.safe_load(DEFAULTS.read_text())
    path = path or local_path()
    if path.is_file():
        settings = merge(settings, yaml.safe_load(path.read_text()) or {})
    return settings


def lookup(settings: dict, dotted: str):
    value = settings
    for part in dotted.split("."):
        value = value[part]
    return value


if __name__ == "__main__":
    print(lookup(load(), sys.argv[1]))

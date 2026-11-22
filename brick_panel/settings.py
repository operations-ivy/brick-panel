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
        local = yaml.safe_load(path.read_text()) or {}
        if not isinstance(local, dict):
            raise ValueError(f"{path}: expected a mapping of settings, got {type(local).__name__}")
        settings = merge(settings, local)
    return settings


def lookup(settings: dict, dotted: str) -> object:
    value = settings
    for part in dotted.split("."):
        value = value[part]
    return value


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python3 -m brick_panel.settings <key.path>", file=sys.stderr)
        return 2
    try:
        print(lookup(load(), argv[1]))
    except (KeyError, TypeError):
        print(f"settings: no such setting {argv[1]!r}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

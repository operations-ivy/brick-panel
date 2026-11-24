"""The panel's sounds: which ones play, how loud, and when it keeps quiet.

The page makes every sound itself (static/sound.js, Web Audio); this holds the
choices behind SETTINGS' checkboxes. The defaults are the settings' sound
section; what's ticked on the panel is saved in its own YAML file beside
settings.yaml (that file holds the token and the code, so the page never
rewrites it), and survives restarts.

Loudness is capped by ALSA on brick1982 (/etc/asound.conf: softvol at most
-25.5 dB); level only picks a gain under that cap. Quiet hours take the
night's window format ("22:00-07:00", or sunset/sunrise ends).
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading
from collections.abc import Callable
from datetime import datetime
from datetime import time as dtime
from pathlib import Path

import yaml

from .night import in_window
from .night import parse_window

log = logging.getLogger(__name__)

# Every sound the page makes, in SETTINGS' order.
EVENTS = (
    "tap",
    "screen",
    "pin_key",
    "pin_ok",
    "pin_bad",
    "alert",
    "surprise_plane",
    "surprise_lights",
    "surprise_sign",
)
# The page's gain for each level, under the ALSA cap: medium is the day level
# the user picked (-30.6 dB with the system volume as saved), low -33.2 dB.
LEVELS = {"low": 0.74, "medium": 1.0}
SWITCHES = ("quiet_sound", "quiet_alerts")  # play anything / alerts in quiet hours


class Sound:
    """SETTINGS' sound choices: the defaults with the saved file laid over
    them. choices is changed only under _lock (the server's threads)."""

    def __init__(
        self,
        defaults: dict,
        path: str | Path,
        sun: Callable[[], dict[str, dtime]] | None = None,
    ) -> None:
        self.path = Path(path).expanduser()
        self.window_text = (defaults.get("quiet_hours") or "").strip()
        self.window = parse_window(self.window_text)
        self.sun = sun or dict
        self._lock = threading.Lock()
        events = defaults.get("events") or {}
        level = defaults.get("level")
        self.choices = {
            "events": {e: bool(events.get(e, True)) for e in EVENTS},
            "level": level if level in LEVELS else "medium",
            **{s: bool(defaults.get(s, False)) for s in SWITCHES},
        }
        self._load()

    @classmethod
    def from_settings(cls, settings: dict, sun: Callable[[], dict[str, dtime]] | None = None) -> Sound:
        s = settings["sound"]
        return cls(s, s["file"], sun)

    def _load(self) -> None:
        """Lay the saved choices over the defaults, keeping only what's valid."""
        try:
            saved = yaml.safe_load(self.path.read_text()) or {}
        except FileNotFoundError:
            return
        except (OSError, yaml.YAMLError) as e:
            log.warning("sound: can't read %s (%s); using the defaults", self.path, e)
            return
        if not isinstance(saved, dict):
            return
        for event, on in (saved.get("events") or {}).items():
            if event in EVENTS and isinstance(on, bool):
                self.choices["events"][event] = on
        if saved.get("level") in LEVELS:
            self.choices["level"] = saved["level"]
        for switch in SWITCHES:
            if isinstance(saved.get(switch), bool):
                self.choices[switch] = saved[switch]

    def _save(self) -> None:
        """Atomically, so a power cut mid-write leaves the old file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".sound-", suffix=".yaml")
        try:
            with os.fdopen(fd, "w") as f:
                f.write("# The panel's sound choices (SETTINGS), written by brick-panel.\n")
                yaml.safe_dump(self.choices, f, sort_keys=False)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def change(self, body: dict) -> tuple[bool, str]:
        """One choice from the page: {"event", "on"}, {"level"}, or
        {"switch", "on"}. (ok, why not)."""
        with self._lock:
            if "event" in body:
                if body["event"] not in EVENTS or not isinstance(body.get("on"), bool):
                    return False, "unknown sound"
                self.choices["events"][body["event"]] = body["on"]
            elif "level" in body:
                if body["level"] not in LEVELS:
                    return False, "unknown level"
                self.choices["level"] = body["level"]
            elif "switch" in body:
                if body["switch"] not in SWITCHES or not isinstance(body.get("on"), bool):
                    return False, "unknown switch"
                self.choices[body["switch"]] = body["on"]
            else:
                return False, "nothing to change"
            try:
                self._save()
            except OSError as e:
                log.warning("sound: can't save %s: %s", self.path, e)
                return False, "couldn't save"
        return True, ""

    def quiet(self, at: datetime | None = None) -> bool:
        return in_window(self.window, at or datetime.now(), self.sun())

    def view(self, at: datetime | None = None) -> dict:
        """The page's copy: the choices, the gain, and whether it's quiet now."""
        with self._lock:
            choices = {**self.choices, "events": dict(self.choices["events"])}
        return {
            **choices,
            "gain": LEVELS[choices["level"]],
            "quiet": self.quiet(at),
            "quiet_window": self.window_text,
        }

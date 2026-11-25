"""Office or guest mode: which of the screen and sound rules apply.

The user, 2026-11-24: brick1982 is in the office, not a bedroom. In office
mode (the default) the screen is always on and the sound never muted on a
timer; a double tap sleeps the screen until a double tap wakes it, and the
mute button mutes until it's pressed again. Guest mode is the night rules
(night.py's window and dim, sound.py's quiet hours), for when the office is
someone's bedroom.

SETTINGS (a tap on the STRAYLIGHT logo) switches it. The choice is saved in
its own YAML file beside settings.yaml, like sound.py's, so it survives
restarts.
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from .metrics import Metrics

log = logging.getLogger(__name__)


class Guest:
    """Whether guest mode is on: the settings' default, or what SETTINGS last
    saved."""

    def __init__(self, default: bool, path: str | Path, metrics: Metrics | None = None) -> None:
        self.path = Path(path).expanduser()
        self.metrics = metrics
        self._lock = threading.Lock()
        self._on = bool(default)
        self._load()
        self._report()

    @classmethod
    def from_settings(cls, settings: dict, metrics: Metrics | None = None) -> Guest:
        g = settings["guest"]
        return cls(g["on"], g["file"], metrics)

    def _load(self) -> None:
        try:
            saved = yaml.safe_load(self.path.read_text()) or {}
        except FileNotFoundError:
            return
        except (OSError, yaml.YAMLError) as e:
            log.warning("guest: can't read %s (%s); using the default", self.path, e)
            return
        if isinstance(saved, dict) and isinstance(saved.get("on"), bool):
            self._on = saved["on"]

    def _save(self, on: bool) -> None:
        """Atomically, so a power cut mid-write leaves the old file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".guest-", suffix=".yaml")
        try:
            with os.fdopen(fd, "w") as f:
                f.write("# Guest mode (SETTINGS), written by brick-panel.\n")
                yaml.safe_dump({"on": on}, f)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def _report(self) -> None:
        if self.metrics:
            self.metrics.set("panel_guest_mode", 1 if self._on else 0)

    def __call__(self) -> bool:
        """True in guest mode: Night and Sound call this to know whether the
        night rules apply."""
        return self._on

    def change(self, body: dict) -> tuple[bool, str]:
        """{"on": bool} from SETTINGS. (ok, why not); unsaved, nothing changes."""
        on = body.get("on")
        if not isinstance(on, bool):
            return False, "on must be true or false"
        with self._lock:
            try:
                self._save(on)
            except OSError as e:
                log.warning("guest: can't save %s: %s", self.path, e)
                return False, "couldn't save"
            self._on = on
            self._report()
        return True, ""

    def view(self) -> dict:
        return {"on": self._on}

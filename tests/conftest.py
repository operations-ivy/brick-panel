from __future__ import annotations

import pytest

from brick_panel import settings as settings_mod


@pytest.fixture(autouse=True)
def no_local_settings(tmp_path, monkeypatch):
    """Tests never read the machine's own ~/.config/brick-panel/settings.yaml."""
    monkeypatch.setenv("BRICK_PANEL_SETTINGS", str(tmp_path / "absent.yaml"))


@pytest.fixture
def settings():
    return settings_mod.load()

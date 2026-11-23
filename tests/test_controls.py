from __future__ import annotations

import pytest

from brick_panel import lock as L
from brick_panel.controls import brightness_pct
from brick_panel.controls import check_setpoints
from brick_panel.controls import Controls
from brick_panel.controls import light_name
from brick_panel.demo import DemoHomeAssistant
from brick_panel.demo import DemoRoom
from brick_panel.metrics import Metrics


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def setup(settings):
    settings["climate"]["pin"] = "2468"
    settings["lights"]["entities"] = {"light.lamp": "Desk"}
    ha, clock, metrics = DemoHomeAssistant(settings), Clock(), Metrics()
    lock = L.PanelLock("2468", idle_seconds=120, clock=clock)
    return Controls(settings, ha, lock, metrics, DemoRoom()), ha, clock, metrics


def test_everything_refused_until_unlocked(setup):
    c, ha, _, metrics = setup
    assert c.set_setpoints({"temperature": 71}) == (False, "locked")
    assert c.set_mode("cool") == (False, "locked")
    assert c.set_light("light.lamp", False) == (False, "locked")
    assert c.unlock("0000")["result"] == L.DENIED
    assert c.unlock("2468")["result"] == L.GRANTED
    assert c.set_setpoints({"temperature": 71}) == (True, "")
    assert ha.attrs("climate.thermostat")["temperature"] == 71
    assert metrics.get("panel_commands_total", action="set_temperature") == 1
    assert metrics.get("panel_unlock_attempts_total", result="denied") == 1


def test_idle_relock(setup):
    c, _, clock, metrics = setup
    c.unlock("2468")
    clock.t += 121
    assert c.view()["lock"]["can_change"] is False
    assert metrics.get("panel_relocks_total", reason="idle") == 1
    assert c.set_mode("cool") == (False, "locked")


def test_secure_counts_only_when_open(setup):
    c, _, _, metrics = setup
    c.secure()
    assert metrics.get("panel_relocks_total", reason="button") == 0
    c.unlock("2468")
    assert c.secure()["can_change"] is False
    assert metrics.get("panel_relocks_total", reason="button") == 1


def test_home_assistant_overrides_the_lock(setup):
    c, ha, _, _ = setup
    ha.states["input_select.lcars_panel_lock"]["state"] = "unlocked"
    assert c.set_mode("cool") == (True, "")
    ha.states["input_select.lcars_panel_lock"]["state"] = "hard_locked"
    assert c.unlock("2468")["result"] == L.HARD
    assert c.set_mode("heat") == (False, "locked")


def test_read_only_refuses_even_when_open(setup):
    c, ha, _, _ = setup
    c.settings["climate"]["read_only"] = True
    ha.states["input_select.lcars_panel_lock"]["state"] = "unlocked"
    assert c.set_mode("cool") == (False, "read only")
    assert c.view()["lock"]["can_change"] is False


def test_no_link_refuses(setup):
    c, ha, _, _ = setup
    c.unlock("2468")
    ha.error = "NO SIGNAL"
    assert c.set_mode("cool") == (False, "no home assistant")


REFUSED = (False, "not a setpoint this mode allows")


@pytest.mark.parametrize(
    "data",
    [
        {"temperature": 90},  # over the guardrail
        {"target_temp_low": 68},  # not a heat-mode key
        {"temperature": "72"},
        {"temperature": True},
        "72",
        {},
    ],
)
def test_bad_setpoints_refused(setup, data):
    c, _, _, _ = setup
    c.unlock("2468")
    assert c.set_setpoints(data) == REFUSED


def test_setpoints_checked_against_mode_and_guardrails(setup):
    c, ha, _, _ = setup
    c.unlock("2468")
    assert c.set_mode("heat_cool") == (True, "")
    assert c.set_setpoints({"target_temp_low": 72}) == REFUSED  # 2 from cool's 74: under the gap
    assert c.set_setpoints({"target_temp_low": 66}) == (True, "")
    attrs = ha.attrs("climate.thermostat")
    assert (attrs["target_temp_low"], attrs["target_temp_high"]) == (66, 74)  # both sent in auto


def test_guardrails_follow_home_assistant(setup):
    c, ha, _, _ = setup
    ha.states["input_number.thermostat_setpoint_max"]["state"] = "72"
    c.unlock("2468")
    assert c.set_setpoints({"temperature": 73}) == REFUSED
    assert c.set_setpoints({"temperature": 72})[0] is True


def test_modes_only_the_thermostat_has(setup):
    c, ha, _, _ = setup
    c.unlock("2468")
    ha.states["climate.thermostat"]["attributes"]["hvac_modes"] = ["heat", "off"]
    assert c.set_mode("cool") == (False, "not a mode this thermostat has")
    assert c.set_mode("off") == (True, "")


def test_lights_only_the_panels(setup):
    c, ha, _, metrics = setup
    c.unlock("2468")
    assert c.set_light("light.kitchen", True) == (False, "not one of the panel's lights")
    assert c.set_light("light.lamp", "yes") == (False, "on must be true or false")
    assert c.set_light("light.lamp", True, 0) == (False, "brightness is 1-100")
    assert c.set_light("light.lamp", True, 101) == (False, "brightness is 1-100")
    assert c.set_light("light.lamp", True, 40) == (True, "")
    assert brightness_pct(ha.attrs("light.lamp")) == 40
    assert c.set_light("light.lamp", False) == (True, "")
    assert ha.value("light.lamp") == "off"
    assert metrics.get("panel_commands_total", action="light_brightness") == 1


def test_view(setup):
    c, _, _, _ = setup
    v = c.view()
    assert v["climate"]["targets"] == ["temperature"]
    assert v["climate"]["house"]["average"] == pytest.approx((71.4 + 68.5) / 2)
    assert v["lights"][0]["name"] == "DESK"
    assert "2468" not in str(v)  # the code never leaves the server


def test_house_without_a_sensor(setup):
    c, _, _, _ = setup
    c.room = None
    house = c.house()
    assert house["average"] is None and house["note"] == "NO UPSTAIRS SENSOR"


def test_check_setpoints_auto_needs_both_known():
    attrs = {"temperature": None, "target_temp_low": None, "target_temp_high": 74}
    assert check_setpoints(attrs, {"target_temp_high": 75}, 64, 76, 5) is None


def test_light_name():
    assert light_name("light.lamp2", {}, {"light.lamp2": "Bedroom"}) == "BEDROOM"
    assert light_name("light.lamp2", {"friendly_name": "Lamp 2"}, {}) == "LAMP 2"
    assert light_name("light.living_room", {}, {}) == "LIVING ROOM"

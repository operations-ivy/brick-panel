from __future__ import annotations

import io
import json
import urllib.error

from brick_panel.homeassistant import HomeAssistant
from brick_panel.metrics import Metrics


class FakeHA:
    """Stands in for urllib.request.urlopen."""

    def __init__(self, states, fail=None):
        self.states, self.fail = states, fail
        self.calls, self.headers = [], []

    def __call__(self, req, timeout):
        self.headers.append(req.get_header("Authorization"))
        if self.fail:
            raise self.fail
        path = req.full_url.split("://", 1)[1].split("/", 1)[1]
        if path == "api/config":
            body = {"unit_system": {"temperature": "°C"}}
        elif path.startswith("api/states/"):
            entity = path.removeprefix("api/states/")
            if entity not in self.states:
                raise urllib.error.HTTPError(req.full_url, 404, "not found", {}, None)
            body = self.states[entity]
        else:
            self.calls.append((path.removeprefix("api/services/"), json.loads(req.data)))
            body = []
        return io.BytesIO(json.dumps(body).encode())


def state(value, **attrs):
    return {"state": value, "attributes": attrs}


def test_poll_reads_states_and_skips_missing_entities():
    fake = FakeHA({"climate.thermostat": state("heat", temperature=70, current_temperature=68.5)})
    m = Metrics()
    ha = HomeAssistant("http://ha/", "tok", ["climate.thermostat", "light.gone", ""], metrics=m, opener=fake)
    assert ha.poll() is True
    assert ha.connected and ha.error == ""
    assert ha.value("climate.thermostat") == "heat"
    assert ha.attrs("climate.thermostat")["current_temperature"] == 68.5
    assert ha.state("light.gone") is None
    assert fake.headers[0] == "Bearer tok"
    assert m.get("panel_ha_up") == 1
    assert m.get("panel_ha_requests_total", kind="state", result="404") == 1


def test_unavailable_reads_as_default():
    fake = FakeHA({"input_number.max": state("unavailable")})
    ha = HomeAssistant("http://ha", "tok", ["input_number.max"], opener=fake)
    ha.poll()
    assert ha.value("input_number.max") is None
    assert ha.number("input_number.max", 76.0) == 76.0


def test_lost_link_keeps_last_states():
    fake = FakeHA({"light.lamp": state("on")})
    m = Metrics()
    ha = HomeAssistant("http://ha", "tok", ["light.lamp"], metrics=m, opener=fake)
    ha.poll()
    fake.fail = OSError("down")
    assert ha.poll() is False
    assert ha.error == "NO SIGNAL" and not ha.connected
    assert ha.value("light.lamp") == "on"
    assert m.get("panel_ha_up") == 0


def test_calls_and_config():
    fake = FakeHA({})
    ha = HomeAssistant("http://ha", "tok", [], opener=fake)
    ha._fetch_config()
    assert ha.unit == "°C"
    ha._call("light", "turn_on", {"entity_id": "light.lamp", "brightness_pct": 40})
    assert fake.calls == [("light/turn_on", {"entity_id": "light.lamp", "brightness_pct": 40})]


def test_failed_call_shows():
    ha = HomeAssistant("http://ha", "tok", [], opener=FakeHA({}, fail=OSError("down")))
    ha._call("light", "turn_off", {"entity_id": "light.lamp"})
    assert ha.error == "COMMAND FAILED"


def test_no_token_never_talks():
    ha = HomeAssistant("http://ha", "", ["light.lamp"], opener=FakeHA({}, fail=AssertionError("called")))
    assert ha.error == "NO TOKEN"
    ha.run()  # returns at once

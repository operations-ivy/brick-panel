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


class FakeLists(FakeHA):
    """Home Assistant with a shopping list and calendars too."""

    def __init__(self, states, items=None, calendars=None, broken=()):
        super().__init__(states)
        self.items, self.calendars, self.broken = items or [], calendars or {}, set(broken)
        self.asked = []

    def __call__(self, req, timeout):
        path = req.full_url.split("://", 1)[1].split("/", 1)[1]
        self.asked.append(path.split("?")[0])
        if path.startswith("api/services/todo/get_items"):
            entity = json.loads(req.data)["entity_id"]
            return io.BytesIO(json.dumps({"service_response": {entity: {"items": self.items}}}).encode())
        if path.startswith("api/calendars/"):
            entity = path.removeprefix("api/calendars/").split("?")[0]
            if entity in self.broken:
                raise urllib.error.URLError("down")
            return io.BytesIO(json.dumps(self.calendars.get(entity, [])).encode())
        return super().__call__(req, timeout)


class Ticker:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def lists_ha(fake, clock, **kw):
    return HomeAssistant("http://ha", "tok", ["sun.sun"], opener=fake, clock=clock, metrics=Metrics(), **kw)


def test_shopping_list_items_on_their_own_schedule():
    items = [{"uid": "a", "summary": "Milk", "status": "needs_action"}, {"summary": "no uid"}]
    fake, clock = FakeLists({"sun.sun": state("above_horizon")}, items=items), Ticker()
    ha = lists_ha(fake, clock, todo="todo.shopping_list", todo_seconds=30)
    assert ha.items() is None
    ha.poll()
    assert ha.items() == [items[0]]
    ha.set_item_status("a", "completed")
    assert ha.items()[0]["status"] == "completed"
    fake.asked.clear()
    ha.poll()  # too soon for the list
    assert "api/services/todo/get_items" not in fake.asked
    ha._call("todo", "update_item", {"entity_id": "todo.shopping_list", "item": "a", "status": "completed"})
    ha.poll()  # straight after a call: fetched again
    assert "api/services/todo/get_items" in fake.asked


def test_calendars_all_or_nothing():
    event = {
        "summary": "Dentist",
        "start": {"dateTime": "2026-11-22T14:00:00-05:00"},
        "end": {"dateTime": "2026-11-22T15:00:00-05:00"},
    }
    fake, clock = FakeLists({}, calendars={"calendar.a": [event], "calendar.b": []}), Ticker()
    ha = lists_ha(fake, clock, calendars=["calendar.a", "calendar.b"], calendar_seconds=300)
    ha.poll()
    assert [e["summary"] for e in ha.events()] == ["Dentist"]
    assert ha.events_age() == 0 and ha.metrics.get("panel_calendar_up") == 1
    fake.broken.add("calendar.b")
    clock.t = 301
    ha.poll()
    assert [e["summary"] for e in ha.events()] == ["Dentist"]  # kept, not half
    assert ha.events_age() == 301 and ha.metrics.get("panel_calendar_up") == 0

from __future__ import annotations

import pytest

from brick_panel.demo import demo_settings
from brick_panel.demo import DemoHomeAssistant
from brick_panel.household import Household
from brick_panel.metrics import Metrics


@pytest.fixture
def setup(settings):
    settings = demo_settings(settings)
    ha, metrics = DemoHomeAssistant(settings), Metrics()
    return Household(settings, ha, metrics), ha, metrics


def test_shopping_list_needed_first(setup):
    h, _, _ = setup
    view = h.shopping_view()
    done = [i["done"] for i in view["items"]]
    assert done == sorted(done) and view["needed"] == done.count(False)


def test_tick_and_untick(setup):
    h, ha, metrics = setup
    uid = h.shopping_view()["items"][0]["uid"]
    assert h.tick(uid, True) == (True, "")
    assert next(i for i in ha.items() if i["uid"] == uid)["status"] == "completed"
    assert h.tick(uid, False) == (True, "")
    assert next(i for i in ha.items() if i["uid"] == uid)["status"] == "needs_action"
    assert metrics.get("panel_commands_total", action="shopping_item") == 2


@pytest.mark.parametrize(
    ("uid", "done", "why"),
    [("item-0", "yes", "done must be true or false"), ("nope", True, "not an item on the list"),
     (7, True, "not an item on the list")],
)
def test_tick_refuses(setup, uid, done, why):
    h, _, _ = setup
    assert h.tick(uid, done) == (False, why)


def test_no_list_no_calendars(setup):
    h, _, _ = setup
    h.settings["shopping"]["entity"] = ""
    h.settings["calendar"]["entities"] = []
    assert h.shopping_view()["available"] is False
    assert h.tick("item-0", True) == (False, "no shopping list")
    assert h.calendar_view() == {"available": False, "message": "NO CALENDARS IN THE SETTINGS"}


def test_calendar_view(setup):
    h, _, metrics = setup
    view = h.calendar_view()
    assert view["available"] and view["stale_minutes"] is None
    assert len(view["months"]) == 2
    assert metrics.get("panel_calendar_events_today") == len(view["days"][view["today"]])


def test_calendar_not_yet_or_stale(setup):
    h, ha, _ = setup
    ha.events = lambda: None
    assert h.calendar_view()["message"] == "CONNECTING TO THE CALENDAR"
    ha.error = "NO SIGNAL"
    assert h.calendar_view()["message"] == "CALENDAR UNAVAILABLE"
    ha.error = ""
    ha.events, ha.events_age = (lambda: []), (lambda: 3600.0)
    assert h.calendar_view()["stale_minutes"] == 60

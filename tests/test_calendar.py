from __future__ import annotations

from datetime import date
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from brick_panel import calendar as cal

TZ = timezone(timedelta(hours=-5))
NOW = datetime(2026, 11, 22, 14, 0, tzinfo=TZ)


def timed(summary, start, minutes=60, **more):
    return {"summary": summary, "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": (start + timedelta(minutes=minutes)).isoformat()}, **more}


def events(*raw):
    return [cal.parse(r, "calendar.home", TZ) for r in raw]


def test_parse_cleans_notes_and_keeps_ids_stable():
    raw = timed("Dentist", NOW, description="<p>Bring the card.</p><p>X-rays &amp; cleaning</p>", location=None)
    e = cal.parse(raw, "calendar.home", TZ)
    assert e["description"] == "Bring the card.\nX-rays & cleaning"
    assert e["location"] == ""
    assert e["id"] == cal.parse(raw, "calendar.home", TZ)["id"]
    assert e["id"] != cal.parse(timed("Other", NOW), "calendar.home", TZ)["id"]
    assert cal.parse({"summary": "bad"}, "calendar.home", TZ) is None
    assert cal.parse(timed("  ", NOW), "c", TZ)["summary"] == "BUSY"


def test_on_day_orders_and_marks_events():
    evs = events(
        timed("Later", NOW + timedelta(hours=3)),
        timed("Soon", NOW + timedelta(minutes=10)),
        timed("Running", NOW - timedelta(minutes=30)),
        timed("Over", NOW - timedelta(hours=4)),
        {"summary": "Bins", "start": {"date": "2026-11-22"}, "end": {"date": "2026-11-23"}},
    )
    day = cal.on_day(evs, NOW.date(), NOW)
    assert [e["summary"] for e in day] == ["Bins", "Over", "Running", "Soon", "Later"]
    by = {e["summary"]: e for e in day}
    assert by["Bins"]["when"] == "ALL DAY"
    assert by["Soon"]["soon"] == 10 and by["Soon"]["when"] == "2:10 PM"
    assert by["Running"]["now"] and not by["Running"]["past"]
    assert by["Over"]["past"]
    assert by["Later"]["soon"] is None
    assert cal.on_day(evs, NOW.date(), NOW, hours=24)[-1]["when"] == "17:00"


def test_an_event_over_midnight_shows_until_on_its_second_day():
    evs = events(timed("Late show", NOW.replace(hour=23), minutes=120))
    assert cal.on_day(evs, NOW.date() + timedelta(days=1), NOW)[0]["when"] == "UNTIL 1:00 AM"


def test_when_lines():
    e = cal.parse(timed("Dentist", NOW), "c", TZ)
    assert cal.when(e) == "SUN 22 NOV, 2:00 PM - 3:00 PM"
    trip = cal.parse({"summary": "Trip", "start": {"date": "2026-11-25"}, "end": {"date": "2026-11-28"}}, "c", TZ)
    assert cal.when(trip) == "WED 25 NOV - FRI 27 NOV, ALL DAY"


def test_window_covers_whole_grids():
    start, end = cal.window(NOW, 2)
    assert start.date() == date(2026, 11, 1)  # a Sunday
    assert end.date() == date(2027, 1, 3)  # the day after December's grid ends
    assert cal.add_months(2026, 12, 1) == (2027, 1)
    assert cal.add_months(2026, 1, -1) == (2025, 12)


def test_view():
    long_notes = "x" * 1000
    evs = events(
        timed("Soon", NOW + timedelta(minutes=5), description=long_notes),
        timed("Over", NOW - timedelta(hours=3)),
        timed("Next month", NOW + timedelta(days=20)),
    )
    v = cal.view(evs, NOW, 2)
    assert [m["name"] for m in v["months"]] == ["NOVEMBER 2026", "DECEMBER 2026"]
    today = next(d for w in v["months"][0]["weeks"] for d in w if d["date"] == "2026-11-22")
    assert today["count"] == 2 and today["tone"] == "now"
    assert v["names"]["2026-11-22"] == "TODAY"
    assert v["today_left"] == 1 and v["next"]["summary"] == "Soon"
    soon = v["next"]["id"]
    assert len(v["events"][soon]["notes"]) == cal.NOTES_MAX
    assert "2026-12-12" in v["days"]
    assert cal.view(None, NOW, 1)["days"] == {}


def test_a_day_all_over_is_past():
    v = cal.view(events(timed("Over", NOW - timedelta(hours=3))), NOW, 1)
    day = next(d for w in v["months"][0]["weeks"] for d in w if d["date"] == "2026-11-22")
    assert day["tone"] == "past"

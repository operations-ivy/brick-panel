"""Calendar events from Home Assistant's calendar API, and what CALENDAR shows
of them: the month grids, each day's events in order, and an event's
details. All-day events come first in a day, then by start time. Titles,
places and notes are for the screen only: they never go to the log or the
metrics. Adapted from rpi_lcars' datasources/calendar.py."""

from __future__ import annotations

import calendar as pycal
import hashlib
import html
import math
import re
from datetime import date
from datetime import datetime
from datetime import time
from datetime import timedelta
from datetime import tzinfo

_BREAK = re.compile(r"<br\s*/?>|</p>|</div>|</li>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
NOTES_MAX = 600  # characters of an event's notes the page gets
SOON_MINUTES = 15


def _when(field: dict, tz: tzinfo) -> tuple[datetime, bool]:
    """(datetime in tz, all_day) from {"dateTime": ...} or {"date": ...}."""
    if "dateTime" in field:
        return datetime.fromisoformat(field["dateTime"]).astimezone(tz), False
    return datetime.combine(date.fromisoformat(field["date"]), time(), tz), True


def _text(value: object) -> str:
    """Plain text from a description, which Google may send as HTML: tags
    out, entities decoded, one line per paragraph, blank lines dropped."""
    text = html.unescape(_TAG.sub("", _BREAK.sub("\n", str(value or ""))))
    return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())


def parse(raw: dict, calendar: str, tz: tzinfo) -> dict | None:
    """An event as Home Assistant sends it -> {"id", "summary", "start", "end",
    "all_day", "location", "description", "calendar"}, or None when it can't
    be read. The id stays the same from one fetch to the next."""
    try:
        start, all_day = _when(raw["start"], tz)
        end, _ = _when(raw["end"], tz)
    except (KeyError, TypeError, ValueError):
        return None
    summary = (raw.get("summary") or "").strip() or "BUSY"
    key = f"{calendar}|{raw.get('uid') or ''}|{start.isoformat()}|{summary}"
    return {
        "id": hashlib.sha1(key.encode(), usedforsecurity=False).hexdigest()[:12],
        "summary": summary,
        "start": start,
        "end": max(end, start),
        "all_day": all_day,
        "location": _text(raw.get("location")),
        "description": _text(raw.get("description")),
        "calendar": calendar,
    }


def grid(year: int, month: int) -> list[list[date]]:
    """The month's weeks, Sunday first, filled out with the days either side."""
    return pycal.Calendar(firstweekday=pycal.SUNDAY).monthdatescalendar(year, month)


def add_months(year: int, month: int, n: int) -> tuple[int, int]:
    """(year, month) n months on (n may be negative)."""
    months = year * 12 + month - 1 + n
    return months // 12, months % 12 + 1


def window(now: datetime, months: int) -> tuple[datetime, datetime]:
    """(start, end) to fetch, in now's zone: the whole grid of this month and
    of the months - 1 after it."""
    first = grid(now.year, now.month)[0][0]
    last = grid(*add_months(now.year, now.month, months - 1))[-1][-1]
    return (
        datetime.combine(first, time(), now.tzinfo),
        datetime.combine(last + timedelta(days=1), time(), now.tzinfo),
    )


def clock(at: datetime, hours: int) -> str:
    """14:30, or 2:30 PM."""
    if hours == 24:
        return f"{at:%H:%M}"
    return f"{at.hour % 12 or 12}:{at:%M} {'AM' if at.hour < 12 else 'PM'}"


def on_day(events: list[dict], day: date, now: datetime, hours: int = 12) -> list[dict]:
    """The day's events, all-day first then by start: each {"id", "summary",
    "when", "all_day", "soon", "now", "past"}. "when" is "ALL DAY", the start,
    or "UNTIL <end>" on a timed event's later days. "soon" is minutes to a
    start within 15; "now" is true while a timed event runs; "past" once it's
    over."""
    begin = datetime.combine(day, time(), now.tzinfo)
    finish = begin + timedelta(days=1)

    def spans_day(e: dict) -> bool:
        return e["all_day"] or (e["start"] < begin and e["end"] >= finish)

    hits = [e for e in events if e["start"] < finish and e["end"] > begin]
    entries = []
    for e in sorted(hits, key=lambda e: (not spans_day(e), e["start"], e["summary"])):
        all_day = spans_day(e)
        if all_day:
            when = "ALL DAY"
        elif e["start"] < begin:
            when = f"UNTIL {clock(e['end'], hours)}"
        else:
            when = clock(e["start"], hours)
        minutes = (e["start"] - now).total_seconds() / 60
        entries.append(
            {
                "id": e["id"],
                "summary": e["summary"],
                "when": when,
                "all_day": all_day,
                "past": e["end"] <= now,
                "soon": math.ceil(minutes) if not all_day and 0 < minutes <= SOON_MINUTES else None,
                "now": not all_day and e["start"] <= now < e["end"],
            }
        )
    return entries


def day_name(day: date, today: date) -> str:
    if day == today:
        return "TODAY"
    if day == today + timedelta(days=1):
        return "TOMORROW"
    return f"{day:%a %-d %b}".upper()


def when(e: dict, hours: int = 12) -> str:
    """An event's date and times in a line: "WED 21 OCT, 2:30 PM - 3:15 PM",
    "WED 21 OCT, ALL DAY", or both ends when it spans days."""
    start, end = e["start"], e["end"]
    if e["all_day"]:
        last = (end - timedelta(days=1)).date() if end > start else start.date()
        if last == start.date():
            return f"{start:%a %-d %b}, ALL DAY".upper()
        return f"{start:%a %-d %b} - {last:%a %-d %b}, ALL DAY".upper()
    if end.date() == start.date():
        return f"{start:%a %-d %b}, {clock(start, hours)} - {clock(end, hours)}".upper()
    return f"{start:%a %-d %b} {clock(start, hours)} - {end:%a %-d %b} {clock(end, hours)}".upper()


def detail(e: dict, hours: int = 12) -> dict:
    """What an event's own view shows."""
    notes = e["description"]
    if len(notes) > NOTES_MAX:
        notes = notes[: NOTES_MAX - 1].rstrip() + "…"
    return {"summary": e["summary"], "when": when(e, hours), "where": e["location"], "notes": notes}


def view(events: list[dict] | None, now: datetime, months: int, hours: int = 12) -> dict:
    """CALENDAR's data: the months from this one ({"key", "name", "weeks"},
    each day {"date", "day", "ours", "count", "tone"}), every day's events
    by ISO date (only days that have some), each event's details by id, and
    the next events to come (for Home's billboard). No events yet: empty."""
    events = events or []
    today = now.date()
    days: dict[str, list[dict]] = {}
    out_months = []
    for n in range(months):
        year, month = add_months(now.year, now.month, n)
        weeks = []
        for week in grid(year, month):
            row = []
            for day in week:
                key = day.isoformat()
                if key not in days:
                    entries = on_day(events, day, now, hours)
                    if entries:
                        days[key] = entries
                entries = days.get(key, [])
                tone = ""
                if any(x["now"] or x["soon"] for x in entries):
                    tone = "now"
                elif entries and all(x["past"] for x in entries):
                    tone = "past"
                row.append(
                    {"date": key, "day": day.day, "ours": day.month == month, "count": len(entries), "tone": tone}
                )
            weeks.append(row)
        out_months.append(
            {"key": f"{year}-{month:02d}", "name": f"{pycal.month_name[month]} {year}".upper(), "weeks": weeks}
        )
    shown = {x["id"] for entries in days.values() for x in entries}
    upcoming = [x for x in days.get(today.isoformat(), []) if not x["past"]]
    return {
        "today": today.isoformat(),
        "today_name": f"{today:%a %-d %b}".upper(),
        "months": out_months,
        "days": days,
        "names": {key: day_name(date.fromisoformat(key), today) for key in days},
        "events": {e["id"]: detail(e, hours) for e in events if e["id"] in shown},
        "today_left": len(upcoming),
        "next": upcoming[0] if upcoming else None,
    }

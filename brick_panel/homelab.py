"""What the ALERTS and BRICK screens show, from the feeds' JSON: Prometheus'
/api/v1/alerts, overwatch's /api/state, brick9000's board /api/state and the
weather service's warnings. Plain functions over plain data, so they're
tested without a page. The alert rules follow LCARS' (rpi_lcars
app/panel/infra.py), so both panels agree on the condition."""

from __future__ import annotations

import re
from datetime import datetime

SEVERITY = {"critical": 0, "warning": 1, "info": 2}
# Prometheus' own plumbing, always firing: not a problem to show.
QUIET = {"Watchdog", "InfoInhibitor"}
# Labels that say where an alert is, best first.
WHERE = ("name", "job", "service", "namespace", "instance")
# Overwatch alerts this recent count as live (its page uses the same 5 min).
LIVE_SECONDS = 300
RECENT_SECONDS = 1800
# The weather service's severities that change the condition.
WEATHER_LEVEL = {"Extreme": 0, "Severe": 1}
CONDITIONS = ("RED", "YELLOW", "GREEN")
# The board's states, worst first.
BOARD_STATES = ("fail", "warn", "unknown", "active", "ok")
BOARD_GROUPS = 6
RECENT_BUILDS = 5
SHIPPED = 3


def words(name: str) -> str:
    """ "KubeProxyDown" -> "KUBE PROXY DOWN", "CPUThrottlingHigh" -> "CPU
    THROTTLING HIGH"."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", name).upper()


def infra_alerts(data: object) -> list[dict] | None:
    """Prometheus' firing alerts, worst then oldest first: [{"text",
    "severity", "since"}]; None while Prometheus hasn't answered."""
    if not isinstance(data, dict):
        return None
    seen, out = set(), []
    for a in data.get("data", {}).get("alerts", []):
        labels = a.get("labels", {})
        name, severity = labels.get("alertname", "?"), labels.get("severity", "none")
        if a.get("state") != "firing" or name in QUIET or severity not in SEVERITY:
            continue
        where = next((labels[k] for k in WHERE if labels.get(k)), "")
        text = f"{words(name)} {where.upper()}".strip()
        if text in seen:
            continue
        seen.add(text)
        out.append({"text": text, "severity": severity, "since": a.get("activeAt", "")})
    return sorted(out, key=lambda a: (SEVERITY[a["severity"]], a["since"]))


def overwatch(data: object, now: float) -> dict | None:
    """{"feeds": [{"name", "word", "line", "severity"}], "recent": [{"text",
    "at", "live"}]}; None while overwatch hasn't answered. Severity is
    overwatch's: 0 all clear, 1 learning, 2 heads up, 3 alert or down."""
    if not isinstance(data, dict):
        return None
    feeds, recent = [], []
    for f in data.get("feeds", []):
        state = f.get("state") or {}
        headline = (state.get("panel") or {}).get("headline") or {}
        name = (f.get("name") or "?").upper()
        if f.get("error"):
            feeds.append({"name": name, "word": "NO SIGNAL", "line": "", "severity": 3})
        else:
            feeds.append(
                {
                    "name": name,
                    "word": (headline.get("word") or "--").upper(),
                    "line": (headline.get("line") or "").upper(),
                    "severity": headline.get("severity", 0),
                }
            )
        for a in state.get("alerts", []):
            age = now - a.get("at", 0)
            if age <= RECENT_SECONDS:
                detail = a.get("detail") or (f"{a['count']} NEARBY" if "count" in a else "")
                label = a.get("label", a.get("kind", "?"))
                recent.append(
                    {"text": f"{label} {detail}".upper().strip(), "at": a.get("at", 0), "live": age <= LIVE_SECONDS}
                )
    recent.sort(key=lambda a: -a["at"])
    return {"feeds": feeds, "recent": recent}


def weather_alerts(alerts: list[dict] | None) -> list[dict] | None:
    """The weather service's warnings, worst first: [{"event", "severity",
    "ends"}] with ends as a timestamp; None when no source with warnings answered."""
    if alerts is None:
        return None
    out = []
    for a in alerts:
        ends = a.get("ends")
        out.append(
            {
                "event": a.get("event", "ALERT"),
                "severity": a.get("severity", "Unknown"),
                "ends": ends.timestamp() if isinstance(ends, datetime) else ends,
            }
        )
    return sorted(out, key=lambda a: WEATHER_LEVEL.get(a["severity"], 2))


def condition(infra: list | None, watch: dict | None, weather: list | None) -> str:
    """RED, YELLOW or GREEN, the worst of the three sources; UNKNOWN when
    none of them has answered."""
    if infra is None and watch is None and weather is None:
        return "UNKNOWN"
    worst = 2
    for a in infra or []:
        worst = min(worst, {"critical": 0, "warning": 1}.get(a["severity"], 2))
    for f in (watch or {}).get("feeds", []):
        worst = min(worst, 0 if f["severity"] >= 3 else 1 if f["severity"] == 2 else 2)
    if any(a["live"] for a in (watch or {}).get("recent", [])):
        worst = 0
    for a in weather or []:
        worst = min(worst, WEATHER_LEVEL.get(a["severity"], 2))
    return CONDITIONS[worst]


def alerts_view(prometheus: object, watch: object, weather: list[dict] | None, now: float) -> dict:
    infra = infra_alerts(prometheus)
    ow = overwatch(watch, now)
    wx = weather_alerts(weather)
    count = (
        len(infra or [])
        + len(wx or [])
        + sum(1 for f in (ow or {}).get("feeds", []) if f["severity"] >= 2)
        + sum(1 for a in (ow or {}).get("recent", []) if a["live"])
    )
    return {"condition": condition(infra, ow, wx), "count": count, "infra": infra, "watch": ow, "weather": wx}


def _state(value: object) -> str:
    return value if value in BOARD_STATES else "unknown"


def brick_view(board: object) -> dict | None:
    """brick9000's board, cut down to what fits the BRICK screen; None while
    the board hasn't answered."""
    if not isinstance(board, dict):
        return None
    groups = []
    for name, group in (board.get("groups") or {}).items():
        checks = group.get("checks") or []
        problems = [
            {"name": c.get("name", "?"), "state": _state(c.get("state")), "detail": c.get("detail", "")}
            for c in checks
            if c.get("state") in ("fail", "warn", "unknown")
        ]
        problems.sort(key=lambda c: BOARD_STATES.index(c["state"]))
        groups.append(
            {
                "name": name.upper(),
                "state": _state(group.get("state")),
                "ok": sum(1 for c in checks if c.get("state") in ("ok", "active")),
                "total": len(checks),
                "problems": problems,
            }
        )
    vitals = [
        {k: v.get(k) for k in ("node", "cpu", "mem", "temp", "disk", "temp_warn")}
        for v in board.get("vitals") or []
        if isinstance(v, dict)
    ]
    recent = [
        {k: r.get(k) for k in ("job", "number", "state", "what")} for r in (board.get("recent") or [])[:RECENT_BUILDS]
    ]
    shipped = [
        {k: s.get(k) for k in ("name", "version", "age", "state")} for s in (board.get("shipped") or [])[:SHIPPED]
    ]
    return {
        "overall": _state(board.get("overall")),
        "groups": groups[:BOARD_GROUPS],
        "vitals": vitals,
        "recent": recent,
        "shipped": shipped,
        "internet": (board.get("host") or {}).get("internet"),
    }

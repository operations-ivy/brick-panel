"""The page Chromium shows, the state it polls, and what it reports back.

GET  /                the page (static/index.html)
GET  /static/<file>   its CSS, scripts and fonts
GET  /api/state       everything the screens show (the weather, the alert
                      condition, the homelab), plus a pending bench run
POST /api/perf        a screen change's frame times
POST /api/bench       ask the page for a bench run (this Pi only); GET: the last result
POST /api/bench/<id>  the page's frames for that run
POST /api/unlock      {"code"}: open the panel lock; /api/secure closes it,
                      /api/touch keeps it open (a tap on the panel)
POST /api/climate     {"setpoints": {...}} or {"mode"}: the thermostat
POST /api/light       {"entity", "on", "pct"?}: a light
POST /api/shopping    {"uid", "done"}: tick a shopping list item off, or back on
POST /api/wake        a tap at night: wakes the screen, says if that's all it did
GET  /room.json       the room sensor's reading, for Home Assistant
GET  /metrics         Prometheus

Every POST that changes something is for the panel's own page only (this
Pi): from anywhere else it's refused, whatever it carries.
"""

from __future__ import annotations

import ipaddress
import json
import mimetypes
import threading
import time
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from . import __version__
from .homelab import alerts_view
from .homelab import brick_view
from .homelab import weather_alerts

if TYPE_CHECKING:
    from .controls import Controls
    from .demo import DemoWeather
    from .feeds import DemoFeed
    from .feeds import JsonFeed
    from .household import Household
    from .metrics import Metrics
    from .night import Night
    from .perf import Perf
    from .weather import Weather

STATIC = (Path(__file__).parent / "static").resolve()
# Changes every start, e.g. after a deploy: the page reloads itself when it
# sees a new one, so it always runs the code the server came with.
BOOT = f"{__version__}-{time.time():.0f}"
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("text/javascript", ".js")
MAX_BODY = 1 << 20
CONTROLS = {"/api/unlock", "/api/secure", "/api/touch", "/api/climate", "/api/light"}
LOCAL_ONLY = {"/api/bench", "/api/shopping", "/api/wake", *CONTROLS}


def is_loopback(client: str) -> bool:
    try:
        return ipaddress.ip_address(client).is_loopback
    except ValueError:
        return False


def static_file(path: str) -> Path | None:
    """The file under STATIC a URL path names, or None (never outside it)."""
    target = (STATIC / path.lstrip("/")).resolve()
    if STATIC not in target.parents or not target.is_file():
        return None
    return target


def control(controls: Controls, path: str, body: dict) -> dict:
    """One control request; the answer always carries the lock's state."""
    if path == "/api/unlock":
        return controls.unlock(body.get("code"))
    if path == "/api/secure":
        return controls.secure()
    if path == "/api/touch":
        controls.touch()
        return controls.lock_view()
    if path == "/api/climate":
        if "mode" in body:
            ok, why = controls.set_mode(body["mode"])
        else:
            ok, why = controls.set_setpoints(body.get("setpoints"))
    elif path == "/api/light":
        ok, why = controls.set_light(body.get("entity"), body.get("on"), body.get("pct"))
    else:
        raise ValueError(f"no control at {path}")
    return {"ok": ok, "why": why, **controls.lock_view()}


def weather_state(weather, alerts: list[dict] | None) -> dict:
    return {
        "current": weather.current(),
        "periods": weather.periods(),
        "alerts": weather_alerts(alerts),
        "age": weather.age(),
        "source": getattr(weather.source, "name", weather.source),
        "error": weather.error,
    }


@dataclass
class Panel:
    """What the handlers need: settings, the data sources, perf and metrics."""

    settings: dict
    weather: Weather | DemoWeather
    perf: Perf
    metrics: Metrics
    feeds: dict[str, JsonFeed | DemoFeed] = field(default_factory=dict)
    controls: Controls | None = None
    household: Household | None = None
    night: Night | None = None

    def screens(self) -> list[str]:
        return ["home", *self.settings["plus"].values(), *self.settings["billboards"]]

    def feed(self, name: str) -> object:
        """A feed's last answer while it's fresh, else None (also when it's off)."""
        f = self.feeds.get(name)
        return f.fresh() if f is not None else None

    def state(self) -> dict:
        s, now = self.settings, time.time()
        warnings = self.weather.alerts()  # once, so WEATHER and ALERTS agree
        return {
            "boot": BOOT,
            "now": now,
            "clock": s["clock"],
            "plus": s["plus"],
            "billboards": s["billboards"],
            "perf": {"budget_ms": self.perf.budget, "late_ms": self.perf.late_after},
            "weather": weather_state(self.weather, warnings),
            "alerts": alerts_view(self.feed("prometheus"), self.feed("overwatch"), warnings, now),
            "brick": brick_view(self.feed("board")),
            "feeds": {name: f.age() for name, f in self.feeds.items()},
            "home": self.controls.view() if self.controls else None,
            "household": self.household.view() if self.household else None,
            "night": self.night.view() if self.night else None,
            "bench": asdict(run) if (run := self.perf.pending()) else None,
        }


def handler(panel: Panel):
    class Handler(BaseHTTPRequestHandler):
        server_version = "brick-panel"

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/api/state":
                if is_loopback(self.client_address[0]):
                    panel.metrics.set("panel_page_seen_timestamp_seconds", time.time())
                return self.send_json(panel.state())
            if path == "/api/bench":
                return self.send_json(asdict(panel.perf.last_bench) if panel.perf.last_bench else {})
            if path == "/room.json":
                room = panel.controls and panel.controls.room
                if not room:
                    return self.send(404, b"no room sensor\n", "text/plain")
                return self.send_json(room.document())
            if path == "/metrics":
                return self.send(200, panel.metrics.render().encode(), "text/plain; version=0.0.4")
            if path == "/":
                path = "/index.html"
            elif path.startswith("/static/"):
                path = path.removeprefix("/static")
            else:
                return self.send(404, b"not found\n", "text/plain")
            target = static_file(path)
            if target is None:
                return self.send(404, b"not found\n", "text/plain")
            kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            # The page reloads on a new BOOT, so nothing may be cached past it.
            self.send(200, target.read_bytes(), kind, cache="no-cache")

        def do_POST(self):
            path = urlsplit(self.path).path
            body = self.read_json()
            if body is None:
                return self.send(400, b"bad json\n", "text/plain")
            if path == "/api/perf":
                smooth = panel.perf.transition(body.get("frames") or [])
                screen = body.get("to")
                if isinstance(screen, str) and screen.isidentifier():
                    for name in panel.screens():
                        panel.metrics.set("panel_screen", 1 if name == screen else 0, screen=name)
                return self.send_json({"smooth": smooth})
            if path in LOCAL_ONLY and not is_loopback(self.client_address[0]):
                return self.send(403, b"only the panel itself can do that\n", "text/plain")
            if path == "/api/bench":
                return self.send_json({"id": panel.perf.request_bench()})
            if path == "/api/wake":
                if panel.night is None:
                    return self.send_json({"woke": False})
                return self.send_json({"woke": panel.night.tap(), **panel.night.view()})
            if path == "/api/shopping":
                if panel.household is None:
                    return self.send(404, b"no shopping list on this panel\n", "text/plain")
                ok, why = panel.household.tick(body.get("uid"), body.get("done"))
                return self.send_json({"ok": ok, "why": why})
            if path in CONTROLS:
                if panel.controls is None:
                    return self.send(404, b"no controls on this panel\n", "text/plain")
                return self.send_json(control(panel.controls, path, body))
            if path.startswith("/api/bench/"):
                result = panel.perf.finish_bench(path.rsplit("/", 1)[1], body.get("frames") or [])
                if result is None:
                    return self.send(409, b"no such bench run\n", "text/plain")
                return self.send_json(asdict(result))
            self.send(404, b"not found\n", "text/plain")

        def read_json(self):
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    return None
                body = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, OSError):
                return None
            return body if isinstance(body, dict) else None

        def send_json(self, data) -> None:
            self.send(200, json.dumps(data, default=str).encode(), "application/json", cache="no-store")

        def send(self, code: int, body: bytes, kind: str, cache: str = "no-store") -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    return Handler


def serve(panel: Panel, host: str, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), handler(panel))
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, name="web", daemon=True).start()
    return server

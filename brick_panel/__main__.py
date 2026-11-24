"""Run the panel's server: python3 -m brick_panel [--demo] [--port N]."""

from __future__ import annotations

import argparse
import logging
import signal
import threading

from . import __version__
from . import feeds as feeds_mod
from . import settings as settings_mod
from .controls import Controls
from .demo import demo_feeds
from .demo import demo_settings
from .demo import DemoHomeAssistant
from .demo import DemoRoom
from .demo import DemoWeather
from .homeassistant import HomeAssistant
from .household import Household
from .metrics import Metrics
from .night import Backlight
from .night import Night
from .night import sun_times
from .perf import Perf
from .room import Room
from .sound import Sound
from .weather import Weather
from .web import Panel
from .web import serve
from .web import surprise_names

log = logging.getLogger("brick_panel")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="brick_panel")
    parser.add_argument("--demo", action="store_true", help="made-up data, no network (for a laptop)")
    parser.add_argument("--port", type=int, help="override server.port")
    parser.add_argument("--host", help="override server.host")
    parser.add_argument("--night", action="store_true", help="with --demo: always night (to try the dark screen)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    settings = settings_mod.load()
    metrics = Metrics()
    metrics.set("panel_info", 1, version=__version__)
    if args.demo:
        settings = demo_settings(settings, night=args.night)
        weather, feeds = DemoWeather(), demo_feeds()
        ha, room = DemoHomeAssistant(settings), DemoRoom()
    else:
        w, h, r = settings["weather"], settings["home_assistant"], settings["room"]
        weather = Weather(w["point"], w["poll_seconds"], metrics=metrics)
        feeds = feeds_mod.from_settings(settings, metrics)
        cal, shop = settings["calendar"], settings["shopping"]
        ha = HomeAssistant(
            h["url"],
            h["token"],
            [*Controls.entities(settings), settings["night"]["sun_entity"]],
            h["poll_seconds"],
            metrics,
            todo=shop["entity"],
            todo_seconds=shop["poll_seconds"],
            calendars=cal["entities"],
            calendar_seconds=cal["poll_seconds"],
            calendar_months=cal["months"],
        )
        room = None
        if r["sensor"]:
            room = Room(r["i2c_bus"], r["i2c_address"], r["offset"], r["poll_seconds"], metrics, chip=r["chip"])
    sources = [weather, *feeds.values(), ha]
    if room is not None:
        sources.append(room)
    for source in sources:
        source.start()
    sun_entity = settings["night"]["sun_entity"]
    backlight = None if args.demo else Backlight()
    night = Night.from_settings(settings, backlight, metrics, sun=lambda: sun_times(ha.attrs(sun_entity)))
    night.start()
    controls = Controls.from_settings(settings, ha, metrics, room, night)
    household = Household(settings, ha, metrics)
    perf = Perf(settings["perf"], metrics)
    sound = Sound.from_settings(settings, sun=lambda: sun_times(ha.attrs(sun_entity)))
    panel = Panel(
        settings, weather, perf, metrics, feeds, controls, household, night, names=surprise_names(), sound=sound
    )
    host = args.host or settings["server"]["host"]
    port = args.port or settings["server"]["port"]
    server = serve(panel, host, port)
    log.info("brick-panel %s on http://%s:%d/%s", __version__, host, port, " (demo)" if args.demo else "")

    done = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: done.set())
    try:
        done.wait()
    except KeyboardInterrupt:
        pass  # Ctrl-C is a normal stop (--demo on a laptop)
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()

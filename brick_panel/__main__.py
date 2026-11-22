"""Run the panel's server: python3 -m brick_panel [--demo] [--port N]."""

from __future__ import annotations

import argparse
import logging
import signal
import threading

from . import __version__
from . import feeds as feeds_mod
from . import settings as settings_mod
from .demo import demo_feeds
from .demo import DemoWeather
from .metrics import Metrics
from .perf import Perf
from .weather import Weather
from .web import Panel
from .web import serve

log = logging.getLogger("brick_panel")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="brick_panel")
    parser.add_argument("--demo", action="store_true", help="made-up data, no network (for a laptop)")
    parser.add_argument("--port", type=int, help="override server.port")
    parser.add_argument("--host", help="override server.host")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    settings = settings_mod.load()
    metrics = Metrics()
    metrics.set("panel_info", 1, version=__version__)
    if args.demo:
        weather, feeds = DemoWeather(), demo_feeds()
    else:
        w = settings["weather"]
        weather = Weather(w["point"], w["poll_seconds"], metrics=metrics)
        feeds = feeds_mod.from_settings(settings, metrics)
    for source in (weather, *feeds.values()):
        source.start()
    panel = Panel(settings, weather, Perf(settings["perf"], metrics), metrics, feeds)
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

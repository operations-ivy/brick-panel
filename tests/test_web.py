"""The real server on a free port, with demo weather."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

import pytest

from brick_panel.demo import DemoWeather
from brick_panel.metrics import Metrics
from brick_panel.perf import Perf
from brick_panel.web import Panel
from brick_panel.web import serve
from brick_panel.web import STATIC
from brick_panel.web import static_file


@pytest.fixture
def server(settings):
    metrics = Metrics()
    panel = Panel(settings, DemoWeather(), Perf(settings["perf"], metrics), metrics)
    srv = serve(panel, "127.0.0.1", 0)
    yield f"http://127.0.0.1:{srv.server_address[1]}", panel
    srv.shutdown()
    srv.server_close()


def get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.headers, r.read()


def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def test_state(server):
    base, _ = server
    status, headers, body = get(base + "/api/state")
    state = json.loads(body)
    assert status == 200 and headers["Cache-Control"] == "no-store"
    assert state["plus"]["up"] == "weather"
    assert state["weather"]["current"]["condition"] == "LIGHT RAIN"
    assert state["bench"] is None
    assert state["boot"]


def test_page_and_everything_it_loads(server):
    base, _ = server
    status, headers, page = get(base + "/")
    assert status == 200 and headers["Content-Type"] == "text/html"
    refs = re.findall(r'(?:href|src)="(/static/[^"]+)"', page.decode())
    assert len(refs) >= 4
    for ref in refs:
        assert get(base + ref)[0] == 200, ref
    css = (STATIC / "theme.css").read_text()
    for font in re.findall(r'url\("([^"]+)"\)', css):
        assert get(base + "/static/" + font)[1]["Content-Type"] == "font/woff2"


def test_nothing_outside_static(server):
    base, _ = server
    for path in ("/static/../web.py", "/static/%2e%2e/web.py", "/nope", "/static/missing.css"):
        with pytest.raises(urllib.error.HTTPError) as e:
            get(base + path)
        assert e.value.code == 404
    assert static_file("../web.py") is None


def test_perf_reports_reach_metrics(server):
    base, panel = server
    assert post(base + "/api/perf", {"from": "home", "to": "weather", "frames": [16.6] * 18}) == {"smooth": True}
    assert post(base + "/api/perf", {"from": "weather", "to": "home", "frames": [16.6, 50]}) == {"smooth": False}
    text = get(base + "/metrics")[2].decode()
    assert 'panel_transitions_total{result="smooth"} 1' in text
    assert 'panel_transitions_total{result="janky"} 1' in text
    assert 'panel_screen{screen="home"} 1' in text
    assert 'panel_screen{screen="weather"} 0' in text


def test_bad_json_is_refused(server):
    base, _ = server
    req = urllib.request.Request(base + "/api/perf", data=b"{nope", headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 400


def test_bench_round_trip(server):
    base, _ = server
    run = post(base + "/api/bench", {})["id"]
    assert json.loads(get(base + "/api/state")[2])["bench"]["id"] == run
    result = post(base + f"/api/bench/{run}", {"frames": [16.6] * 300})
    assert result["passed"] is True
    assert json.loads(get(base + "/api/bench")[2])["id"] == run
    assert json.loads(get(base + "/api/state")[2])["bench"] is None
    with pytest.raises(urllib.error.HTTPError) as e:
        post(base + f"/api/bench/{run}", {"frames": [16.6]})
    assert e.value.code == 409

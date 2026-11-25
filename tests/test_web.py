"""The real server on a free port, with demo weather."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

import pytest

from brick_panel.controls import Controls
from brick_panel.demo import demo_feeds
from brick_panel.demo import demo_settings
from brick_panel.demo import DemoHomeAssistant
from brick_panel.demo import DemoRoom
from brick_panel.demo import DemoWeather
from brick_panel.guest import Guest
from brick_panel.household import Household
from brick_panel.metrics import Metrics
from brick_panel.night import Night
from brick_panel.perf import Perf
from brick_panel.sound import Sound
from brick_panel.web import is_loopback
from brick_panel.web import Panel
from brick_panel.web import serve
from brick_panel.web import STATIC
from brick_panel.web import static_file
from brick_panel.web import surprise_names


def make_panel(settings, feeds=None, controls=None, metrics=None, household=None, night=None):
    metrics = metrics or Metrics()
    perf = Perf(settings["perf"], metrics)
    return Panel(settings, DemoWeather(), perf, metrics, feeds or {}, controls, household, night)


@pytest.fixture
def server(settings):
    settings, metrics = demo_settings(settings, night=True), Metrics()
    ha = DemoHomeAssistant(settings)
    night = Night(settings["night"]["window"], 0.6, 1.0, 300, metrics=metrics)
    controls = Controls.from_settings(settings, ha, metrics, DemoRoom(), night)
    panel = make_panel(settings, demo_feeds(), controls, metrics, Household(settings, ha, metrics), night)
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
    assert state["alerts"]["condition"] == "YELLOW"
    assert state["alerts"]["infra"][0]["text"] == "TARGET DOWN LCARS"
    assert state["brick"]["overall"] == "warn"
    assert set(state["feeds"]) == {"board", "prometheus", "overwatch"}


def test_state_without_feeds(settings):
    state = make_panel(settings).state()
    assert state["brick"] is None
    assert state["alerts"]["condition"] == "GREEN"  # the demo weather answered: no warnings
    assert state["alerts"]["infra"] is None and state["alerts"]["watch"] is None


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


def test_controls_through_the_server(server):
    base, panel = server
    post(base + "/api/double-tap", {})  # the fixture's always night: awake, or dark locks the controls
    assert post(base + "/api/climate", {"mode": "cool"})["why"] == "locked"
    assert post(base + "/api/unlock", {"code": "1982"})["result"] == "granted"
    answer = post(base + "/api/climate", {"setpoints": {"temperature": 72}})
    assert answer["ok"] and answer["can_change"]
    assert post(base + "/api/light", {"entity": "light.lamp", "on": False})["ok"]
    assert post(base + "/api/secure", {})["can_change"] is False
    state = json.loads(get(base + "/api/state")[2])
    assert state["home"]["climate"]["setpoints"]["temperature"] == 72
    assert state["home"]["lights"][0]["on"] is False


def test_shopping_and_calendar_through_the_server(server):
    base, _ = server
    state = json.loads(get(base + "/api/state")[2])
    items = state["household"]["shopping"]["items"]
    assert state["household"]["calendar"]["available"]
    first = items[0]
    assert post(base + "/api/shopping", {"uid": first["uid"], "done": True}) == {"ok": True, "why": ""}
    assert post(base + "/api/shopping", {"uid": "nope", "done": True})["ok"] is False
    state = json.loads(get(base + "/api/state")[2])
    assert next(i for i in state["household"]["shopping"]["items"] if i["uid"] == first["uid"])["done"]


def test_a_double_tap_through_the_server(server):
    base, _ = server
    assert json.loads(get(base + "/api/state")[2])["night"]["dark"] is True
    assert post(base + "/api/wake", {})["awake"] is False  # a single touch doesn't wake it
    answer = post(base + "/api/double-tap", {})
    assert answer["awake"] is True
    assert answer["dark"] is False
    assert post(base + "/api/wake", {})["awake"] is True
    assert post(base + "/api/double-tap", {})["awake"] is False


def test_going_dark_locks_the_controls(server):
    base, panel = server
    post(base + "/api/double-tap", {})
    assert post(base + "/api/unlock", {"code": "1982"})["result"] == "granted"
    panel.night._awake_until = 0  # the wake runs out
    assert json.loads(get(base + "/api/state")[2])["home"]["lock"]["unlocked"] is False
    assert panel.metrics.get("panel_relocks_total", reason="dark") == 1


def test_room_json(server):
    base, _ = server
    assert json.loads(get(base + "/room.json")[2]) == {
        "up": True,
        "temperature_f": 71.4,
        "humidity": 41.0,
        "pressure_hpa": 1016.2,
    }


@pytest.mark.parametrize(
    "path",
    [
        "/api/unlock",
        "/api/secure",
        "/api/touch",
        "/api/climate",
        "/api/light",
        "/api/bench",
        "/api/shopping",
        "/api/wake",
        "/api/double-tap",
        "/api/mute",
        "/api/rum",
        "/api/sound",
        "/api/guest",
    ],
)
def test_controls_are_for_the_panel_only(server, monkeypatch, path):
    base, _ = server
    monkeypatch.setattr("brick_panel.web.is_loopback", lambda client: False)  # as if from the LAN
    with pytest.raises(urllib.error.HTTPError) as e:
        post(base + path, {"code": "1982", "mode": "cool"})
    assert e.value.code == 403


def test_is_loopback():
    assert is_loopback("127.0.0.1") and is_loopback("::1")
    assert not is_loopback("192.168.1.50") and not is_loopback("nonsense")


def test_surprise_names():
    assert surprise_names("alpha, Bravo ,charlie") == ["ALPHA", "BRAVO", "CHARLIE"]
    assert surprise_names("o'neil-smith,b,c") == ["ONEILSMI", "B", "C"]  # letters only, at most 8
    assert surprise_names("") == []
    assert surprise_names("alpha,bravo") == []  # three or none


def test_surprise_names_only_for_the_panel_itself(settings):
    panel = make_panel(settings)
    panel.names = ["ALPHA", "BRAVO", "CHARLIE"]
    assert panel.state(local=True)["names"] == ["ALPHA", "BRAVO", "CHARLIE"]
    assert panel.state()["names"] == []  # a browser on the LAN never sees them


@pytest.fixture
def sound_server(settings, tmp_path):
    panel = make_panel(settings)
    panel.sound = Sound(settings["sound"], tmp_path / "sound.yaml")
    srv = serve(panel, "127.0.0.1", 0)
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def test_state_has_the_sound_choices(sound_server):
    assert json.loads(get(sound_server + "/api/state")[2])["sound"]["events"]["tap"] is True


def test_a_sound_choice_is_kept(sound_server):
    answer = post(sound_server + "/api/sound", {"event": "tap", "on": False})
    assert answer["ok"]
    assert answer["sound"]["events"]["tap"] is False
    assert json.loads(get(sound_server + "/api/state")[2])["sound"]["events"]["tap"] is False


def test_a_bad_sound_choice_is_refused(sound_server):
    answer = post(sound_server + "/api/sound", {"level": "eleven"})
    assert not answer["ok"]
    assert answer["sound"]["level"] == "medium"


def test_no_sound_is_a_404(server):
    base, panel = server
    assert panel.sound is None
    with pytest.raises(urllib.error.HTTPError) as e:
        post(base + "/api/sound", {"level": "low"})
    assert e.value.code == 404


def test_the_mute_button(sound_server):
    before = json.loads(get(sound_server + "/api/state")[2])["sound"]["muted"]
    assert post(sound_server + "/api/mute", {})["sound"]["muted"] == (not before)
    assert json.loads(get(sound_server + "/api/state")[2])["sound"]["muted"] == (not before)


@pytest.fixture
def guest_server(settings, tmp_path):
    panel = make_panel(settings)
    panel.guest = Guest(False, tmp_path / "guest.yaml", panel.metrics)
    panel.night = Night("00:00-23:59", 0.6, 1.0, 300, guest=panel.guest)  # always night, in guest mode
    panel.sound = Sound({**settings["sound"], "quiet_hours": "00:00-23:59"}, tmp_path / "sound.yaml", guest=panel.guest)
    srv = serve(panel, "127.0.0.1", 0)
    yield f"http://127.0.0.1:{srv.server_address[1]}", panel
    srv.shutdown()
    srv.server_close()


def test_guest_mode_switches_the_night_rules(guest_server):
    base, panel = guest_server
    state = json.loads(get(base + "/api/state")[2])
    assert state["guest"] == {"on": False}
    assert state["night"]["dark"] is False and state["sound"]["muted"] is False  # office: on, sound
    answer = post(base + "/api/guest", {"on": True})
    assert answer["ok"] and answer["guest"] == {"on": True}
    assert answer["night"]["dark"] is True and answer["sound"]["muted"] is True  # guest: the night rules
    assert "panel_guest_mode 1" in get(base + "/metrics")[2].decode()


def test_a_bad_guest_mode_is_refused(guest_server):
    base, _ = guest_server
    answer = post(base + "/api/guest", {"on": "yes"})
    assert not answer["ok"] and answer["guest"] == {"on": False}

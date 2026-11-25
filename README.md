# brick-panel

brick1982's neon wall panel: the 7" Raspberry Pi touchscreen in the bedroom,
in portrait (480x800, the panel turned 90 degrees clockwise). It's the full
version of the [Presto](https://github.com/operations-ivy/presto)'s neon desk
display, in the look of brick9000's board and brick-games. It replaces the
LCARS panel ([rpi_lcars](https://github.com/operations-ivy/rpi_lcars)), which
stays installed; `panel-select` switches between them.

A small Python server on the Pi serves the page and its data. Chromium shows
it full screen under cage. Everything runs on the Pi itself, not on k3s: a
bedroom alerts panel has to keep working when the cluster it watches is down,
and it holds the panel's own sensor, PIN and Home Assistant token.

## The plus

```
                 [ WEATHER ]
                      ^
  [ BRICK ]  <    [ HOME ]    >  [ CLIMATE ]
                      v
                  [ LIGHTS ]
```

Home is a rainy neon city at night: a neon-tube clock that glitches every
20-30 s, the date, the forecast, and a skyline whose weather follows the real
one (rain when it rains, stars on a clear night). Billboards on the rooftops
open **CALENDAR** and **SHOPPING**, and **ALERTS** hangs on chains from the
top edge. Arms and billboards are settings (`plus`, `billboards`,
`hanging`).

| Touch | Does |
| --- | --- |
| On Home, swipe (left pulls in the screen on the right; the green arrows say what's where) | slides to that arm's screen |
| On Home, tap a billboard | zooms into its screen |
| On an arm, swipe back towards Home (the HOME arrow's side comes in) | back to Home |
| In a billboard's screen, swipe up or down | back to Home |
| Two-finger tap | Home, from anywhere |

The screens:

- **WEATHER**: now (conditions, humidity, wind), the weather service's
  warnings, the next three days' temperatures as one line, and six forecast
  periods with rain chances.
- **BRICK**: brick9000's board on the wall: each node's CPU, memory,
  temperature and disk, the board's groups (cluster, builds, Argo CD,
  services, wigle) with their first problem, the latest builds and what
  shipped.
- **ALERTS**: the alert condition (GREEN, YELLOW, RED), the worst of
  Prometheus' firing alerts, overwatch's feeds and recent alerts, and the
  weather service's warnings (Extreme is RED, Severe is YELLOW). It follows
  LCARS' rules, so both panels agree. The billboard on Home shows how many
  things need a look.

- **CLIMATE**: the house (the room sensor upstairs, the ecobee downstairs,
  their average, the humidity), what the system is doing, the setpoints on
  Home Assistant's guardrails, big arrows for the setpoint (two in auto,
  kept the gap apart), and the modes.
- **LIGHTS**: each light in `lights.entities` with its brightness, - and +,
  and on/off.

- **CALENDAR**: Home Assistant's calendars (`calendar.entities`): the month
  as a grid (a dot per event, today outlined), and an agenda from the day
  tapped (today at first) on through the days after. Events starting within
  15 minutes or running now are amber; a tap opens one's time, place and
  notes. This month and next. The billboard shows what's left today, or
  counts down to the next event.
- **SHOPPING**: Home Assistant's to-do list (`shopping.entity`), needed
  first; a tap ticks an item off or back on, paged 8 at a time. Open to
  anyone, as on LCARS (it isn't the thermostat), but still only items on the
  list, from the Pi itself.

Titles, places and notes never go to the log or the metrics.

## Home's surprises

Every few minutes, one of three: a plane crosses the sky towing a banner,
the city's windows drift together into letters and apart again, or the
tower's BRICK sign shorts out and comes back as a word for a few seconds.
Each spells a name from `BRICK_PANEL_NAMES` (three, comma separated, e.g.
`BRICK_PANEL_NAMES=ALPHA,BRAVO,CHARLIE`). They're people's names, so they live
only in the panel's env file (`~/.config/brick-panel/env`), never in git, and
the server gives them only to the panel's own page, never to a browser on
the LAN. Not set (or not three): no surprises. `deploy/bench` times them too.

## Real user monitoring

The page reports how it's doing every 30 s (`static/rum.js`, `rum.py`), as
`panel_rum_*` metrics: each tap's time to the next frame (fast under 100 ms,
ok under 200 ms, slow), long tasks, a few seconds of frames sampled each
minute on the screen that's up, errors (also logged, so in Loki), memory,
uptime, and how long the state polls take.

## Night, and when the screen is on

The user's rules (2026-11-23, 2026-11-24), in `night.py`, `sound.py` and
`guest.py`. brick1982 is in the office, so it runs in **office mode** unless
**guest mode** is switched on (SETTINGS, a tap on the STRAYLIGHT logo:
OFFICE / GUEST; saved in `~/.config/brick-panel/guest.yaml`, the default is
`guest.on`).

**Office mode (the default):** the screen is always on at
`night.day_level`. A double tap sleeps it until a double tap wakes it; no
night, dim or morning changes that. The sound is never muted on a timer;
the mute button mutes it until it's pressed again.

**Guest mode** is the night rules below, for when the office is someone's
bedroom. Switching to it at night puts the screen to sleep; switching back
wakes it. Switching drops the mute button's flip.

- **A double tap always sleeps the screen, or wakes it.** It counts only
  on an empty spot, not on a button, billboard or key, so nothing is
  pressed twice. Asleep, the backlight is off and the page black, Home,
  still. Going dark locks the controls.
- **18:00-07:00 (`night.window`): asleep unless double-tapped awake.** A
  single tap doesn't wake it. Awake, it sleeps again 5 minutes
  (`night.idle_seconds`) after the last touch, or on a double tap.
- **Woken 22:00-07:00 (`night.dim`):** the backlight at `night.level`
  (60%).
- **By day:** on at `night.day_level`. A double tap sleeps it until a
  double tap wakes it, or 07:00 does.
- **Sound** is muted 18:00-08:00 (`sound.quiet_hours`). The mute button
  in the bottom-left corner of every screen (no code needed) unmutes it
  until 08:00, or by day mutes it until 18:00.

Either end of a window can be `sunset` or `sunrise` (Home Assistant's
`sun.sun`); empty is never. The backlight level is `panel_backlight_level`
in Prometheus, double taps are `panel_double_taps_total`, and the mode is
`panel_guest_mode` (1: guest).

There is no slideshow, and won't be: no photos on brick1982 (the user,
2026-11-22).

## The controls and the lock

CLIMATE and LIGHTS change things in Home Assistant, so they're locked, as
LCARS' are (the same rules, `lock.py`). Looking is free; changing needs the
code (`climate.pin`). The keypad's digits are shuffled every time it opens,
so watching a hand teaches nothing. Three wrong codes lock the keypad out
for 30 s, doubling each time up to 10 min. The panel relocks after 2 min
without a touch, or at SECURE. Home Assistant's
`input_select.lcars_panel_lock` overrides it on both panels: `unlocked`
needs no code, `hard_locked` refuses even the right one. `climate.read_only`
shows everything and changes nothing.

The page decides nothing. Every change is a request to the server, which
takes it only from the Pi itself (from anywhere else it's 403, whatever it
carries), and only while the lock allows it. A setpoint must be one the
thermostat's mode has, inside the guardrails, auto's pair at least
`climate.heat_cool_gap` apart. A light must be one of the panel's. Taps show
at once and gather for 1.5 s before one call goes to Home Assistant.

`/room.json` serves the room sensor's reading for Home Assistant's
`sensor.bedroom_*`, as LCARS' did: `up`, `temperature_f`, `humidity`, and
`pressure_hpa` (null on an SHT3x). The sensor is an SHT3x at 0x44 or the
Pimoroni Multi-Sensor Stick's BME280 at 0x76 (`room.chip`), read straight from
`/dev/i2c-1` with no packages: the BME280 with its own calibration and Bosch's
floating-point formulas, in forced mode every 30 s.

## Smooth screen changes

Smooth screen changes are the first requirement, so the page is built around them:

- Only `transform` and `opacity` animate (Web Animations API), so the
  compositor moves screens without layout or paint.
- Every screen is its own layer, always painted and stacked under the live
  one. A change never waits for a first paint, and covered screens' animations are paused.
- Home's skyline is painted once into a canvas. Rain, stars, windows and the
  flying car are static layers moved by CSS animations, so the main thread
  draws nothing per frame.
- The page times every frame of every screen change and posts them to
  `/api/perf`. They show up in Prometheus as `panel_transitions_total{result="smooth|janky"}`
  and `panel_transition_frames_total{result="on_time|late"}`. A frame over
  `frame_budget_ms x late_factor` (25 ms) missed a vsync.
- `deploy/bench` runs on brick1982 with the panel showing. It drives the
  page round the plus and through every billboard three times, then fails if
  the p95 frame is over 20 ms or over 5% of frames are late. First run on
  brick1982 (Pi 4, Chromium 154): 731 frames, p95 16.7 ms, worst 16.8 ms,
  0 late. With WEATHER, BRICK and ALERTS built (PR 2), three runs: 742, 737
and 734 frames, the same p95 and worst, 0 late. With CLIMATE and LIGHTS on
live Home Assistant data (PR 3), six runs: p95 16.7 ms each time; one run
had one dropped frame (33 ms, 0.3% late), the other five none. With CALENDAR,
SHOPPING, the billboards' rigs and their flicker (PR 4), three runs: 750, 754
and 754 frames, p95 16.7 ms, worst 16.8 ms, 0 late.

## Settings

`brick_panel/defaults.yaml` lists every setting with its default. A panel
changes one by putting just that key in `~/.config/brick-panel/settings.yaml`
(not in git), which is merged over the defaults. The weather's `point`
(where the panel is) only ever goes there.

```yaml
weather:
  point: "lat,lon"
home_assistant:
  token: "..."    # the Panel user's long-lived token
climate:
  pin: "..."
lights:
  entities:
    light.lamp: Office
calendar:
  entities: [calendar.home]   # its name can say where the house is: only here
room:
  sensor: true
  chip: bme280    # the Multi-Sensor Stick; sht3x for an SHT30/31/35
kiosk:
  rotation: 90    # if the panel is turned the other way
```

The token and the code only ever go in that file (mode 600), never in git.

`python3 -m brick_panel.settings kiosk.rotation` prints one value.

`feeds.sources` are the homelab pages the panel reads: the board
(`status.brick.nozdormu.cloud/api/state`), Prometheus' alerts and
overwatch, each polled on its own thread. An empty `url` turns one off. A
feed's last answer is shown for `feeds.stale_seconds` after its source stops
answering, then that part of the screen reads OFFLINE. Each feed's health is
`panel_feed_up{feed}` in Prometheus.

## On a laptop

```
poetry install
poetry run python -m brick_panel --demo --port 8799 --host 127.0.0.1
```

Open `http://127.0.0.1:8799/` in a 480x800 window. `--demo` uses made-up
weather, homelab and Home Assistant (the code is 1982; it does what it's told). To open a screen directly, add its name as a hash, like
`http://127.0.0.1:8799/#weather`. Tests: `poetry run pytest`.
Style: `poetry run pre-commit run --all-files`.

## On brick1982

```
git clone https://github.com/operations-ivy/brick-panel.git ~/brick-panel
~/brick-panel/deploy/install.sh     # installs, doesn't switch
panel-select neon                   # or: panel-select lcars
~/brick-panel/deploy/bench          # are screen changes smooth?
```

- `brick-panel.service` is the server, on :8767, the port LCARS used, so
  Prometheus' job keeps its target.
- `brick-panel-kiosk.service` runs cage on tty1 and `deploy/kiosk`. That
  script turns the output with `wlr-randr --transform` and starts Chromium
  with GPU raster. cage doesn't turn the touchscreen with the output, so
  before it starts, `deploy/touch-rotation` writes a udev rule giving
  libinput the calibration matrix for `kiosk.rotation`
  (`/etc/udev/rules.d/91-brick-panel-touch.rules`).
- `panel-select` switches between the neon panel and LCARS. Only one runs at
  a time, and only that panel's deploy timer is on.
- `brick-panel-deploy.timer` (a user unit, every 2 hours) follows
  `BRICK_PANEL_DEPLOY_BRANCH` in `~/.config/brick-panel/env` (`main` by
  default), which Jenkins' `deploy-brick-panel` job sets (brick-cicd-config;
  don't edit it by hand). It tests the new commit in a scratch
  worktree, switches only if the tests pass, and restarts the server. The
  page sees the server's new start and reloads itself. Rerun
  `deploy/install.sh` after a change under `deploy/`.
- Screenshot over ssh:
  `XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-0 grim /tmp/x.png`.

## Style

`static/theme.css` is the homelab's neon look in one file: the Presto's
palette merged with brick-status and brick-games', and the VT323 and
Silkscreen fonts, bundled (OFL, licences in `static/fonts/`). Square
corners, neon glows, the magenta/cyan glitch split, scanlines, and TV static
on a billboard zoom.

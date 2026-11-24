// brick1982's panel: the plus, its screen changes, and the data on them.
//
// Screen changes are the point of this file (the user: smooth transitions
// above all). Each one animates only transform/opacity with the Web
// Animations API, which runs on the compositor; the page times every frame
// of it and reports to the server (/api/perf -> Prometheus), so a janky
// change is a number on a graph, not a feeling.
"use strict";

const W = 480, H = 800;
const SLIDE = { duration: 300, easing: "cubic-bezier(.2,.75,.2,1)", fill: "forwards" };
const ZOOM = { duration: 280, easing: "cubic-bezier(.2,.75,.2,1)", fill: "forwards" };
const POLL_MS = 5000;
// Where each arm lies from Home: [dx, dy] in screens.
const ARM = { up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0] };
const OPPOSITE = { up: "down", down: "up", left: "right", right: "left" };
const stage = document.getElementById("stage");
const screens = {};
for (const el of stage.querySelectorAll(".screen")) screens[el.dataset.screen] = el;
const home = screens.home;
const hints = document.getElementById("hints");
const staticEl = document.getElementById("static");
const nightEl = document.getElementById("night");

let state = null;
let current = "home";
let busy = false;
let plus = { up: "weather", right: "climate", down: "lights", left: "brick" };
let billboards = ["alerts", "calendar", "shopping"];
let hanging = "alerts";

// ---- Frame timing ----

function recordFrames() {
  const frames = [];
  let last = 0, on = true;
  const tick = (t) => {
    if (!on) return;
    if (last) frames.push(t - last);
    last = t;
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
  return () => { on = false; return frames; };
}

function post(path, body) {
  return fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
    .then((r) => r.json()).catch(() => null);
}

// ---- Screen changes ----

// Where `name` sits relative to Home: an arm direction, "billboard", or null.
function placeOf(name) {
  for (const [dir, arm] of Object.entries(plus)) if (arm === name) return dir;
  // SETTINGS opens out of the logo like a billboard's app, and closes the same way.
  return billboards.includes(name) || name === "settings" ? "billboard" : null;
}

function slide(from, to, dx, dy) {
  to.classList.add("incoming");
  const a = from.animate([{ transform: "translate3d(0,0,0)" },
    { transform: `translate3d(${-dx * W}px,${-dy * H}px,0)` }], SLIDE);
  const b = to.animate([{ transform: `translate3d(${dx * W}px,${dy * H}px,0)` },
    { transform: "translate3d(0,0,0)" }], SLIDE);
  return Promise.all([a.finished, b.finished]).then(() => [a, b]);
}

function billboardOrigin(name) {
  const b = name === "settings" ? home.querySelector(".logo") : home.querySelector(`.billboard[data-open="${name}"]`);
  if (!b) return "50% 70%";
  return `${b.offsetLeft + b.offsetWidth / 2}px ${b.offsetTop + b.offsetHeight / 2}px`;
}

function zoom(from, to, opening, name) {
  const app = opening ? to : from;
  app.style.transformOrigin = billboardOrigin(name);
  to.classList.add("incoming");
  if (!opening) { // the app shrinks back into its billboard, over Home
    from.classList.add("incoming");
    to.classList.add("live");
    to.classList.remove("incoming");
  }
  const small = { transform: "scale(.18)", opacity: 0 }, full = { transform: "scale(1)", opacity: 1 };
  const a = app.animate(opening ? [small, full] : [full, small], ZOOM);
  flashStatic();
  return a.finished.then(() => [a]);
}

function flashStatic() {
  staticEl.animate([
    { opacity: 0, transform: "translate3d(0,0,0)" },
    { opacity: 0.22, transform: "translate3d(-37px,-61px,0)", offset: 0.3 },
    { opacity: 0.12, transform: "translate3d(-91px,-13px,0)", offset: 0.6 },
    { opacity: 0, transform: "translate3d(0,0,0)" },
  ], { duration: 180, easing: "steps(6)" });
}

async function go(name) {
  if (busy || name === current || !screens[name]) return null;
  busy = true;
  const from = screens[current], to = screens[name];
  const stop = recordFrames();
  hints.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 90, fill: "forwards" });

  let anims;
  if (current === "home" || name === "home") {
    const other = current === "home" ? name : current;
    const place = placeOf(other);
    if (place === "billboard") {
      anims = await zoom(from, to, name !== "home", other);
    } else {
      const [dx, dy] = ARM[place] || [0, 1];
      anims = name === "home" ? await slide(from, to, -dx, -dy) : await slide(from, to, dx, dy);
    }
  } else { // app to app (two-finger tap lands here only via Home)
    anims = await slide(from, to, 0, 1);
  }

  // Settle: the new screen is live, the old one goes back under it.
  to.classList.add("live");
  to.classList.remove("incoming");
  from.classList.remove("live", "incoming");
  for (const a of anims) a.cancel();
  from.style.transformOrigin = to.style.transformOrigin = "";
  current = name;
  drawHints();
  hints.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 120, fill: "forwards" });
  leaveControls(from.dataset.screen);
  leaveHousehold(from.dataset.screen);
  if (name !== "home") Pizazz.stop(); // Home's covered now
  if (name === "home") renderClock(true);

  const frames = stop();
  busy = false;
  return frames;
}

async function goAndReport(name) {
  const from = current;
  if (!busy && name !== current && screens[name]) Sfx.play("screen");
  const frames = await go(name);
  if (frames) post("/api/perf", { from, to: name, frames });
}

// ---- Night ----
// The server decides when the screen sleeps (night.py: the user's rules); the
// page follows it. Asleep, it goes Home, stops its animations, and only a
// double tap on it does anything. awakeUntil is the page's own copy of the
// server's idle time at night, so it goes dark on time between polls.

let awakeUntil = 0, dark = false, lastWake = 0;

function screenDark() {
  const n = state && state.night;
  if (!n) return false;
  return n.is_night ? performance.now() >= awakeUntil : n.dark;
}

// The server's view of the screen, from a poll or a double tap's answer.
function takeNight(view) {
  if (!state || !view || view.is_night === undefined) return;
  state.night = view;
  awakeUntil = view.is_night ? performance.now() + (view.awake_for || 0) * 1000 : 0;
}

function applyDark() {
  const d = screenDark();
  if (d === dark || busy) return;
  dark = d;
  stage.classList.toggle("dark", d);
  nightEl.animate([{ opacity: d ? 0 : 1 }, { opacity: d ? 1 : 0 }], { duration: d ? 900 : 160, fill: "forwards" });
  if (d) {
    Pizazz.stop();
    leaveControls(current);
    leaveHousehold(current);
    jump("home");
  } else {
    render();
  }
}

// A double tap: sleep the screen, or wake it.
async function doubleTap() {
  takeNight(await post("/api/double-tap", {}));
  applyDark();
}

// A touch on the awake screen: at night, its 5 minutes start again (told to
// the server at most every 5 s).
function nightTouch() {
  const n = state && state.night;
  if (!n || !n.is_night) return;
  awakeUntil = performance.now() + n.idle_seconds * 1000;
  if (performance.now() - lastWake > 5000) {
    lastWake = performance.now();
    post("/api/wake", {});
  }
}

// ---- Touch ----

function hintsFor(name) {
  if (name === "home") {
    return Object.entries(plus).map(([dir, arm]) => ({ dir, text: TITLES[arm] || arm.toUpperCase(), cls: "" }));
  }
  return [{ dir: backOf(name), text: "HOME", cls: "home" }];
}

function drawHints() {
  hints.innerHTML = hintsFor(current).map(({ dir, text, cls }) => {
    const arrow = `<b class="tri ${dir}"></b>`, label = `<span>${text}</span>`;
    const parts = dir === "down" || dir === "right" ? label + arrow : arrow + label;
    return `<div class="hint ${dir} ${cls}">${dir === "right" ? arrow + label : parts}</div>`;
  }).join("");
}

// A swipe: the finger's travel, if it went far enough, mostly one way.
const SWIPE_PX = 50, SWIPE_MS = 700;
function swipeDir(dx, dy) {
  const ax = Math.abs(dx), ay = Math.abs(dy);
  if (Math.max(ax, ay) < SWIPE_PX) return null;
  if (ax > ay * 1.5) return dx < 0 ? "left" : "right";
  if (ay > ax * 1.5) return dy < 0 ? "up" : "down";
  return null;
}

// Swiping drags the plus: a swipe left brings in the screen on the right,
// as if pulling it into view. On an app, the swipe that pulls Home back in
// (towards its HOME arrow's opposite) goes Home; a billboard's app closes
// with a swipe up or down.
function swipe(dir) {
  if (busy) return;
  const toward = OPPOSITE[dir];
  if (current === "home") {
    if (plus[toward]) goAndReport(plus[toward]);
  } else if (toward === backOf(current) || (placeOf(current) === "billboard" && (dir === "up" || dir === "down"))) {
    goAndReport("home");
  }
}

// A tap presses a button or opens a billboard; screens change by swiping.
function tap(target) {
  if (target.closest && target.closest("#mute")) return toggleMute(); // on every screen, even mid-change
  if (busy) return;
  const button = current !== "home" && target.closest && target.closest("[data-act]");
  if (!(button && button.dataset.act === "keypad-digit")) Sfx.play("tap"); // a code key has its own
  if (current === "home" && target.closest && target.closest(".topbar")) return goAndReport("settings");
  if (button && screens[current].contains(button)) {
    if (!button.disabled && ACTIONS[button.dataset.act]) ACTIONS[button.dataset.act](button.dataset.arg, button);
    return;
  }
  const board = target.closest && target.closest(".billboard");
  if (current === "home" && board) {
    board.classList.add("pressed");
    setTimeout(() => board.classList.remove("pressed"), 140);
    return goAndReport(board.dataset.open);
  }
}

const pointers = new Map();
const PRESS = [{ transform: "scale(.93)" }, { transform: "scale(1)" }];
// A double tap: two quick taps close together, on an empty spot (not on
// anything a tap presses, so nothing is pressed twice). Asleep, anywhere.
const DOUBLE_MS = 400, DOUBLE_PX = 48;
let lastTap = null;
function emptySpot(target) {
  return !(target.closest && target.closest("button, [data-act], .billboard, .topbar, #mute"));
}

stage.addEventListener("pointerdown", (e) => {
  const asleep = dark;
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY, t: e.timeStamp, asleep });
  if (asleep) return;
  nightTouch();
  touched();
  const button = e.target.closest && e.target.closest("[data-act]");
  if (button && !button.disabled) button.animate(PRESS, { duration: 160, easing: "cubic-bezier(.2,.75,.2,1)" });
  if (pointers.size >= 2) { pointers.clear(); goAndReport("home"); }
});
stage.addEventListener("pointerup", (e) => {
  const p = pointers.get(e.pointerId);
  pointers.delete(e.pointerId);
  if (!p) return;
  const dx = e.clientX - p.x, dy = e.clientY - p.y;
  const moved = Math.hypot(dx, dy);
  if (moved < 24 && e.timeStamp - p.t < 800) {
    const spot = p.asleep || emptySpot(e.target);
    if (spot && lastTap && e.timeStamp - lastTap.t < DOUBLE_MS &&
        Math.hypot(e.clientX - lastTap.x, e.clientY - lastTap.y) < DOUBLE_PX) {
      lastTap = null;
      doubleTap();
      return;
    }
    lastTap = spot ? { t: e.timeStamp, x: e.clientX, y: e.clientY } : null;
    if (p.asleep) return; // asleep, a single tap does nothing
    tap(e.target);
    RUM.tap(e.timeStamp);
  }
  else if (!p.asleep && e.timeStamp - p.t < SWIPE_MS) {
    const dir = swipeDir(dx, dy);
    if (dir) swipe(dir);
  }
});
stage.addEventListener("pointercancel", (e) => pointers.delete(e.pointerId));
stage.addEventListener("contextmenu", (e) => e.preventDefault());

// ---- Rendering ----

let lastMinute = "";
function renderClock(force) {
  const now = new Date();
  const hours24 = (state && state.clock && state.clock.hours === 24);
  let h = now.getHours();
  const ampm = hours24 ? "" : h < 12 ? "AM" : "PM";
  if (!hours24) h = h % 12 || 12;
  const text = `${hours24 ? String(h).padStart(2, "0") : h}:${String(now.getMinutes()).padStart(2, "0")}`;
  if (text === lastMinute && !force) return;
  lastMinute = text;
  const t = home.querySelector(".time");
  setText(t, text);
  t.dataset.text = text;
  setText(home.querySelector(".ampm"), ampm);
  const days = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];
  const months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
  setText(home.querySelector(".date"), `${days[now.getDay()]} ${now.getDate()} ${months[now.getMonth()]}`);
}

function glitchSoon() {
  setTimeout(() => {
    if (current === "home" && !busy) {
      const t = home.querySelector(".time");
      t.classList.remove("glitch");
      void t.offsetWidth;
      t.classList.add("glitch");
    }
    glitchSoon();
  }, 20000 + Math.random() * 10000);
}

const BILLBOARD_TEXT = { alerts: alertsBillboard, calendar: calendarBillboard, shopping: shoppingBillboard };

function renderHome() {
  const w = state.weather || {};
  const cur = w.current || {};
  const next = (w.periods || [])[0];
  setText(home.querySelector(".forecast .temp"), deg(cur.temperature));
  setText(home.querySelector(".forecast .cond"), cur.condition || (w.error ? w.error : "NO SIGNAL"));
  const nextHtml = next ? `<b>${esc(next.name)}</b> ${deg(next.temperature)} ${esc(next.forecast)}` : "";
  const nextEl = home.querySelector(".forecast .next");
  if (nextEl.innerHTML !== nextHtml) nextEl.innerHTML = nextHtml;
  Scene.weather(home, cur.condition || (next && next.forecast) || "", isNight());

  for (const b of home.querySelectorAll(".billboard")) {
    const val = b.querySelector(".val");
    const show = BILLBOARD_TEXT[b.dataset.open];
    const { text, lit } = show ? show(state) : { text: "--", lit: false };
    setText(val, text);
    b.classList.toggle("lit", lit);
  }
}

// The edge a screen's HOME arrow is on.
function backOf(name) {
  const place = placeOf(name);
  return place === "billboard" ? "down" : OPPOSITE[place] || "down";
}

function render() {
  if (!state) return;
  renderHome();
  renderWeather(screens.weather, state, backOf("weather"));
  renderBrick(screens.brick, state, backOf("brick"));
  renderAlerts(screens.alerts, state, backOf("alerts"));
  renderControls();
  renderHousehold();
  renderSettings(screens.settings, state, backOf("settings"));
  renderMute();
}

// ---- State ----

let boot = null;
let benchSeen = null;
let alertsSeen = null; // the last alert count, so a new alert sounds once
let hashDone = false;

async function poll() {
  try {
    const asked = performance.now();
    const r = await fetch("/api/state", { cache: "no-store" });
    const s = await r.json();
    RUM.poll(performance.now() - asked);
    if (boot && s.boot !== boot) { location.reload(); return; }
    boot = s.boot;
    state = s;
    plus = s.plus || plus;
    const count = s.alerts && s.alerts.condition !== "UNKNOWN" ? s.alerts.count || 0 : null;
    if (count !== null) {
      if (alertsSeen !== null && count > alertsSeen) Sfx.play("alert");
      alertsSeen = count;
    }
    if (JSON.stringify(s.billboards) !== JSON.stringify(billboards) || s.hanging !== hanging) {
      billboards = s.billboards;
      hanging = s.hanging;
      Scene.build(home, billboards, hanging);
    }
    takeNight(s.night);
    home.querySelector(".link").classList.remove("down");
    setText(home.querySelector(".link-text"), "LINK");
    applyDark();
    if (!busy && !dark) render();
    if (!busy) Pizazz.prepare();
    if (!hashDone) { hashDone = true; if (location.hash.length > 1) jump(location.hash.slice(1)); }
    if (s.bench && s.bench.id !== benchSeen) { benchSeen = s.bench.id; bench(s.bench); }
  } catch (e) {
    home.querySelector(".link").classList.add("down");
    setText(home.querySelector(".link-text"), "NO LINK");
  }
}

// ---- Bench ----

// Round the plus and through every billboard, `rounds` times, then Home's
// three surprises, timing every frame; deploy/bench asked for it and reads
// the verdict.
async function bench(run) {
  Sfx.hush(true);
  try { await benchRun(run); } finally { Sfx.hush(false); }
}

async function benchRun(run) {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const tour = [];
  for (const arm of Object.values(plus)) tour.push(arm, "home");
  for (const b of billboards) tour.push(b, "home");
  if (current !== "home") await go("home");
  const frames = [];
  for (let i = 0; i < run.rounds; i++) {
    for (const name of tour) {
      await wait(160);
      const f = await go(name);
      if (f) frames.push(...f);
    }
  }
  // Then Home's surprises, each timed while it plays (when there are names).
  if (current !== "home") await go("home");
  for (let i = 0; i < 3; i++) {
    await wait(300);
    const stop = recordFrames();
    if (Pizazz.play(i)) await Pizazz.wait();
    const f = stop();
    if (f.length > 2) frames.push(...f.slice(1));
  }
  post(`/api/bench/${run.id}`, { frames });
}

// A screen straight away, no animation: for previews (index.html#weather),
// and Home when the screen goes dark.
function jump(name) {
  if (!screens[name] || name === current) return;
  screens[current].classList.remove("live");
  screens[name].classList.add("live");
  current = name;
  drawHints();
}

// ---- Start ----

Scene.build(home, billboards, hanging);
drawHints();
renderClock(true);
setInterval(() => renderClock(false), 1000);
glitchSoon();
Pizazz.start(home);
RUM.start();
poll();
setInterval(poll, POLL_MS);
setInterval(applyDark, 1000);

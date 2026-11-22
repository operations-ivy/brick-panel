// brick1982's panel: the plus, its screen changes, and the data on them.
//
// Screen changes are the point of this file (the user: smooth transitions
// above all). Each one animates only transform/opacity with the Web
// Animations API, which runs on the compositor; the page times every frame
// of it and reports to the server (/api/perf -> Prometheus), so a janky
// change is a number on a graph, not a feeling.
"use strict";

const W = 480, H = 800, BAND = 64;
const SLIDE = { duration: 300, easing: "cubic-bezier(.2,.75,.2,1)", fill: "forwards" };
const ZOOM = { duration: 280, easing: "cubic-bezier(.2,.75,.2,1)", fill: "forwards" };
const POLL_MS = 5000;
// Where each arm lies from Home: [dx, dy] in screens.
const ARM = { up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0] };
const OPPOSITE = { up: "down", down: "up", left: "right", right: "left" };
// What each screen will hold, until its PR lands.
const COMING = {
  climate: "The thermostat: set point, mode and the room, behind the PIN and the lock key.",
  lights: "Home Assistant's lights: on, off and brightness.",
  calendar: "The household calendar: today, then the weeks ahead.",
  shopping: "The shopping list: tick things off, see what's left.",
};

const stage = document.getElementById("stage");
const screens = {};
for (const el of stage.querySelectorAll(".screen")) screens[el.dataset.screen] = el;
const home = screens.home;
const hints = document.getElementById("hints");
const staticEl = document.getElementById("static");

let state = null;
let current = "home";
let busy = false;
let plus = { up: "weather", right: "climate", down: "lights", left: "brick" };
let billboards = ["alerts", "calendar", "shopping"];

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
  return billboards.includes(name) ? "billboard" : null;
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
  const b = home.querySelector(`.billboard[data-open="${name}"]`);
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
  if (name === "home") renderClock(true);

  const frames = stop();
  busy = false;
  return frames;
}

async function goAndReport(name) {
  const from = current;
  const frames = await go(name);
  if (frames) post("/api/perf", { from, to: name, frames });
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

function bandAt(x, y) {
  if (y < BAND) return "up";
  if (y > H - BAND) return "down";
  if (x < BAND) return "left";
  if (x > W - BAND) return "right";
  return null;
}

function tap(x, y, target) {
  if (busy) return;
  const board = target.closest && target.closest(".billboard");
  if (current === "home" && board) {
    board.classList.add("pressed");
    setTimeout(() => board.classList.remove("pressed"), 140);
    return goAndReport(board.dataset.open);
  }
  const band = bandAt(x, y);
  if (!band) return;
  if (current === "home") {
    if (plus[band]) goAndReport(plus[band]);
  } else if (hintsFor(current).some((h) => h.dir === band)) {
    goAndReport("home");
  }
}

const pointers = new Map();
stage.addEventListener("pointerdown", (e) => {
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY, t: e.timeStamp });
  if (pointers.size >= 2) { pointers.clear(); goAndReport("home"); }
});
stage.addEventListener("pointerup", (e) => {
  const p = pointers.get(e.pointerId);
  pointers.delete(e.pointerId);
  if (!p) return;
  const r = stage.getBoundingClientRect();
  const moved = Math.hypot(e.clientX - p.x, e.clientY - p.y);
  if (moved < 24 && e.timeStamp - p.t < 800) tap(e.clientX - r.left, e.clientY - r.top, e.target);
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
    if (b.dataset.open === "alerts") {
      const { text, lit } = alertsBillboard(state);
      setText(val, text);
      b.classList.toggle("lit", lit);
    } else {
      setText(val, b.dataset.open === "calendar" ? "AGENDA" : "LIST");
    }
  }
}

// The edge a screen's HOME arrow is on.
function backOf(name) {
  const place = placeOf(name);
  return place === "billboard" ? "down" : OPPOSITE[place] || "down";
}

function renderComing(name) {
  const place = placeOf(name);
  const shell = appShell(screens[name], name, backOf(name));
  setText(shell.kicker, "BRICK//1982 // " + (place === "billboard" ? "BILLBOARD" : "ARM"));
  paint(shell.body, `<div class="panel-box"><span class="tab">STANDBY</span><div class="body soon">
    ${esc(COMING[name] || "")}<br><br><b>// NOT WIRED UP YET</b></div></div>`);
}

function render() {
  if (!state) return;
  renderHome();
  renderWeather(screens.weather, state, backOf("weather"));
  renderBrick(screens.brick, state, backOf("brick"));
  renderAlerts(screens.alerts, state, backOf("alerts"));
  for (const name of Object.keys(COMING)) renderComing(name);
}

// ---- State ----

let boot = null;
let benchSeen = null;
let hashDone = false;

async function poll() {
  try {
    const r = await fetch("/api/state", { cache: "no-store" });
    const s = await r.json();
    if (boot && s.boot !== boot) { location.reload(); return; }
    boot = s.boot;
    state = s;
    plus = s.plus || plus;
    if (JSON.stringify(s.billboards) !== JSON.stringify(billboards)) {
      billboards = s.billboards;
      Scene.build(home, billboards);
    }
    home.querySelector(".link").classList.remove("down");
    setText(home.querySelector(".link-text"), "LINK");
    if (!busy) render();
    if (!hashDone) { hashDone = true; if (location.hash.length > 1) jump(location.hash.slice(1)); }
    if (s.bench && s.bench.id !== benchSeen) { benchSeen = s.bench.id; bench(s.bench); }
  } catch (e) {
    home.querySelector(".link").classList.add("down");
    setText(home.querySelector(".link-text"), "NO LINK");
  }
}

// ---- Bench ----

// Round the plus and through every billboard, `rounds` times, timing every
// frame; deploy/bench asked for it and reads the verdict.
async function bench(run) {
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
  post(`/api/bench/${run.id}`, { frames });
}

// A screen straight away, no animation: for previews (index.html#weather).
function jump(name) {
  if (!screens[name] || name === current) return;
  screens[current].classList.remove("live");
  screens[name].classList.add("live");
  current = name;
  drawHints();
}

// ---- Start ----

Scene.build(home, billboards);
drawHints();
renderClock(true);
setInterval(() => renderClock(false), 1000);
glitchSoon();
poll();
setInterval(poll, POLL_MS);

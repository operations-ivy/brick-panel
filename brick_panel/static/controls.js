// CLIMATE and LIGHTS: the screens that change things, and their keypad.
//
// The server decides everything (the lock, read-only, the guardrails, which
// lights): the page only shows what it's told and asks. Taps show at once and
// gather for send_after_ms before one request goes; what was sent shows until
// Home Assistant reports it (or CONFIRM_MS pass), as on LCARS. Nothing here
// animates but transform and opacity.
"use strict";

const CONFIRM_MS = 15000;
const TOUCH_EVERY_MS = 5000;
const MODE_NAMES = { heat: "HEAT", cool: "COOL", heat_cool: "AUTO", off: "OFF" };
const TARGET_NAMES = { target_temp_low: "HEAT TO", target_temp_high: "COOL TO" };

// What's in flight, per screen.
const flight = {
  climate: { pending: {}, timer: null, sent: {}, sentAt: 0, mode: null, modeAt: 0 },
  lights: { pending: {}, timer: null, sent: {} }, // sent: entity -> { values, at }
};
let lastTouch = 0;

function hass() {
  return (state && state.home) || null;
}

function now() {
  return performance.now();
}

// ---- Talking to the server ----

async function ask(path, body) {
  const answer = await post(path, body || {});
  setTimeout(poll, 700); // Home Assistant's answer, soon
  return answer;
}

// Any tap on the panel while it's open keeps it open (the server relocks
// after a quiet spell).
function touched() {
  const h = hass();
  if (!h || !h.lock.unlocked || now() - lastTouch < TOUCH_EVERY_MS) return;
  lastTouch = now();
  post("/api/touch", {});
}

// ---- Setpoints (setpoints.py's step(), for showing a tap at once) ----

function clamp(v, lo, hi) {
  return Math.min(Math.max(v, lo), hi);
}

function step(shown, target, delta, lo, hi, gap) {
  if (target === "temperature") {
    const t = shown.temperature;
    if (t === null || t === undefined) return null;
    const v = clamp(t + delta, lo, hi);
    return v === t ? null : { temperature: v };
  }
  const low = shown.target_temp_low, high = shown.target_temp_high;
  if (low === null || low === undefined || high === null || high === undefined) return null;
  let newLow, newHigh;
  if (target === "target_temp_low") {
    newLow = clamp(low + delta, lo, hi - gap);
    newHigh = clamp(Math.max(high, newLow + gap), lo, hi);
  } else {
    newHigh = clamp(high + delta, lo + gap, hi);
    newLow = clamp(Math.min(low, newHigh - gap), lo, hi);
  }
  return newLow === low && newHigh === high ? null : { target_temp_low: newLow, target_temp_high: newHigh };
}

function climateShown(h) {
  const f = flight.climate, c = h.climate;
  if (f.sent && now() - f.sentAt > CONFIRM_MS) f.sent = {};
  if (Object.keys(f.sent).every((k) => c.setpoints[k] === f.sent[k])) f.sent = {};
  if (f.mode && (now() - f.modeAt > CONFIRM_MS || c.mode === f.mode)) f.mode = null;
  return { setpoints: { ...c.setpoints, ...f.sent, ...f.pending }, mode: f.mode || c.mode };
}

function nudge(target, delta) {
  const h = hass();
  if (!h || !h.lock.can_change) return;
  const c = h.climate, [lo, hi] = c.guardrails;
  const data = step(climateShown(h).setpoints, target, delta, lo, hi, c.gap);
  if (!data) return;
  const f = flight.climate;
  Object.assign(f.pending, data);
  clearTimeout(f.timer);
  f.timer = setTimeout(flushClimate, h.send_after_ms);
  renderClimate(screens.climate, state, backOf("climate"));
}

function flushClimate() {
  const f = flight.climate;
  clearTimeout(f.timer);
  if (!Object.keys(f.pending).length) return;
  const setpoints = f.pending;
  f.pending = {};
  f.sent = { ...f.sent, ...setpoints };
  f.sentAt = now();
  ask("/api/climate", { setpoints });
}

function setMode(mode) {
  const h = hass();
  if (!h || !h.lock.can_change || mode === climateShown(h).mode) return;
  flushClimate();
  const f = flight.climate;
  f.mode = mode;
  f.modeAt = now();
  f.sent = {};
  ask("/api/climate", { mode });
  renderClimate(screens.climate, state, backOf("climate"));
}

// ---- Lights ----

function lightShown(light) {
  const f = flight.lights, out = { ...light };
  const sent = f.sent[light.entity];
  if (sent) {
    const done = Object.entries(sent.values).every(([k, v]) => light[k] === v);
    if (done || now() - sent.at > CONFIRM_MS) delete f.sent[light.entity];
    else Object.assign(out, sent.values);
  }
  if (light.entity in f.pending) Object.assign(out, { on: true, pct: f.pending[light.entity] });
  return out;
}

function toggleLight(entity) {
  const h = hass();
  const light = h && h.lights.find((l) => l.entity === entity);
  if (!light || !light.available || !h.lock.can_change) return;
  const shown = lightShown(light);
  delete flight.lights.pending[entity];
  const on = !shown.on;
  flight.lights.sent[entity] = { values: { on }, at: now() };
  ask("/api/light", { entity, on });
  renderLights(screens.lights, state, backOf("lights"));
}

function stepLight(entity, delta) {
  const h = hass();
  const light = h && h.lights.find((l) => l.entity === entity);
  if (!light || !light.available || !h.lock.can_change) return;
  const shown = lightShown(light);
  const was = shown.on && shown.pct !== null ? shown.pct : 0;
  const pct = Math.min(100, Math.max(h.step_pct, was + delta)); // - stops at the lowest step; off is the toggle
  if (pct === was) return;
  const f = flight.lights;
  f.pending[entity] = pct;
  clearTimeout(f.timer);
  f.timer = setTimeout(flushLights, h.send_after_ms);
  renderLights(screens.lights, state, backOf("lights"));
}

function flushLights() {
  const f = flight.lights;
  clearTimeout(f.timer);
  for (const [entity, pct] of Object.entries(f.pending)) {
    f.sent[entity] = { values: { on: true, pct }, at: now() };
    ask("/api/light", { entity, on: true, pct });
  }
  f.pending = {};
}

// ---- The keypad: digits shuffled every time it opens ----

const keypads = {};

function shuffledDigits() {
  const d = [..."0123456789"];
  const r = new Uint32Array(d.length);
  crypto.getRandomValues(r);
  for (let i = d.length - 1; i > 0; i--) {
    const j = r[i] % (i + 1);
    [d[i], d[j]] = [d[j], d[i]];
  }
  return d;
}

function keypadFor(el) {
  const name = el.dataset.screen;
  if (keypads[name]) return keypads[name];
  const pad = document.createElement("div");
  pad.className = "keypad";
  pad.innerHTML = `<div class="kp-head">ENTER CODE</div><div class="kp-dots"></div><div class="kp-msg"></div>
    <div class="kp-keys">${Array.from({ length: 12 }, (_, i) => `<button class="key kp-key" data-i="${i}"></button>`).join("")}</div>
    <button class="key kp-cancel" data-act="keypad-cancel">CANCEL</button>`;
  el.appendChild(pad);
  const k = { el: pad, open: false, code: "", flash: "", flashUntil: 0, name };
  keypads[name] = k;
  return k;
}

function openKeypad(name) {
  const k = keypadFor(screens[name]);
  const digits = shuffledDigits();
  const labels = [...digits.slice(0, 9), "CLEAR", digits[9], "ENTER"];
  k.el.querySelectorAll(".kp-key").forEach((b, i) => {
    const label = labels[i];
    b.textContent = label;
    b.dataset.act = label === "CLEAR" ? "keypad-clear" : label === "ENTER" ? "keypad-enter" : "keypad-digit";
    b.dataset.arg = label;
    b.className = `key kp-key ${label === "CLEAR" ? "clear" : label === "ENTER" ? "enter" : ""}`;
  });
  k.code = "";
  k.flash = "";
  k.open = true;
  k.el.classList.add("open");
  k.el.animate([{ opacity: 0, transform: "translate3d(0,24px,0)" }, { opacity: 1, transform: "translate3d(0,0,0)" }],
    { duration: 180, easing: "cubic-bezier(.2,.75,.2,1)" });
  renderKeypad(k);
}

function closeKeypad(name, animate = true) {
  const k = keypads[name];
  if (!k || !k.open) return;
  k.open = false;
  k.code = "";
  if (!animate) { k.el.classList.remove("open"); return; }
  k.el.animate([{ opacity: 1, transform: "translate3d(0,0,0)" }, { opacity: 0, transform: "translate3d(0,24px,0)" }],
    { duration: 140, easing: "ease-in" }).finished.then(() => { if (!k.open) k.el.classList.remove("open"); });
}

function renderKeypad(k) {
  const h = hass();
  const lock = h ? h.lock : null;
  let msg = "AUTHORIZED PERSONNEL ONLY", tone = "", usable = true;
  if (!lock) { msg = "NO HOME ASSISTANT"; tone = "bad"; usable = false; }
  else if (lock.remote === "hard_locked") { msg = "LOCKED BY HOME ASSISTANT"; tone = "bad"; usable = false; }
  else if (!lock.has_pin) { msg = "NO CODE SET: UNLOCK FROM HOME ASSISTANT"; tone = "bad"; usable = false; }
  else if (lock.lockout > 0) {
    msg = `SECURITY LOCKOUT ${Math.floor(lock.lockout / 60)}:${String(lock.lockout % 60).padStart(2, "0")}`;
    tone = "bad"; usable = false;
  } else if (k.flash && now() < k.flashUntil) { msg = k.flash; tone = "bad"; }
  setText(k.el.querySelector(".kp-msg"), msg);
  k.el.querySelector(".kp-msg").className = `kp-msg ${tone}`;
  paint(k.el.querySelector(".kp-dots"), Array.from({ length: 8 }, (_, i) => `<i class="${i < k.code.length ? "on" : ""}"></i>`).join(""));
  k.el.querySelectorAll(".kp-key").forEach((b) => { b.disabled = !usable; });
  if (!usable) k.code = "";
}

async function enterCode(k) {
  const code = k.code;
  k.code = "";
  renderKeypad(k);
  const answer = await post("/api/unlock", { code });
  if (!answer) return;
  if (state && state.home) state.home.lock = { ...state.home.lock, ...answer, result: undefined };
  if (answer.result === "granted") {
    Sfx.play("pin_ok");
    lastTouch = now();
    closeKeypad(k.name);
    renderControls();
    return;
  }
  if (answer.result === "denied") {
    Sfx.play("pin_bad");
    const left = answer.misses_left;
    k.flash = `ACCESS DENIED: ${left} ATTEMPT${left === 1 ? "" : "S"} LEFT`;
    k.flashUntil = now() + 4000;
  }
  renderKeypad(k);
}

// ---- Actions (buttons with data-act; panel.js dispatches taps) ----

const ACTIONS = {
  "nudge-up": (target) => nudge(target, 1),
  "nudge-down": (target) => nudge(target, -1),
  mode: (mode) => setMode(mode),
  "light-toggle": (entity) => toggleLight(entity),
  "light-up": (entity) => stepLight(entity, hass() ? hass().step_pct : 10),
  "light-down": (entity) => stepLight(entity, -(hass() ? hass().step_pct : 10)),
  unlock: () => openKeypad(current),
  secure: async () => {
    flushClimate();
    flushLights();
    const answer = await post("/api/secure", {});
    if (answer && state && state.home) state.home.lock = { ...state.home.lock, ...answer };
    renderControls();
  },
  "keypad-digit": (d) => {
    const k = keypads[current];
    if (k && k.code.length < 8) { k.code += d; renderKeypad(k); Sfx.play("pin_key"); }
  },
  "keypad-clear": () => { const k = keypads[current]; if (k) { k.code = ""; renderKeypad(k); } },
  "keypad-enter": () => { const k = keypads[current]; if (k && k.code) enterCode(k); },
  "keypad-cancel": () => closeKeypad(current),
};

// Leaving CLIMATE or LIGHTS: send what's gathered, close the keypad.
function leaveControls(name) {
  if (name === "climate") flushClimate();
  if (name === "lights") flushLights();
  closeKeypad(name, false);
}

// ---- Rendering ----

function lockBar(h) {
  const lock = h.lock;
  let button = "", line, note, tone;
  if (h.link) {
    [line, note, tone] = ["HOME ASSISTANT OFFLINE", h.link, "bad"];
  } else if (lock.read_only) {
    [line, note, tone] = ["PREVIEW ONLY", "CONTROLS DISABLED", "warn"];
  } else if (lock.can_change) {
    button = `<button class="key big secure" data-act="secure">SECURE</button>`;
    [line, note, tone] = ["CONTROLS OPEN", lock.remote === "unlocked" ? "OPENED BY HOME ASSISTANT" : "SECURE WHEN DONE", "warn"];
  } else if (lock.remote === "hard_locked") {
    [line, note, tone] = ["CONTROLS LOCKED", "BY HOME ASSISTANT", "bad"];
  } else {
    button = `<button class="key big unlock" data-act="unlock">UNLOCK</button>`;
    [line, note, tone] = ["CONTROLS SECURED", "UNLOCK TO ADJUST", "ok"];
  }
  return `<div class="lockbar ${tone}">${button}<div class="lockmsg"><b>${esc(line)}</b><span>${esc(note)}</span></div></div>`;
}

function lockBadge(shell, h) {
  if (!h) return badge(shell.badge, "NO TOKEN", "dim");
  const lock = h.lock;
  if (lock.read_only) return badge(shell.badge, "PREVIEW", "dim");
  if (lock.remote === "hard_locked") return badge(shell.badge, "HA LOCKED", "bad");
  if (lock.can_change) return badge(shell.badge, "UNLOCKED", "warn");
  return badge(shell.badge, "SECURED", "ok");
}

function fmt(v, unit = "°") {
  if (v === null || v === undefined) return "--";
  return Number.isInteger(v) ? `${v}${unit}` : `${v.toFixed(1)}${unit}`;
}

function scale(c, shown, keys) {
  const [lo, hi] = c.guardrails, span = Math.max(hi - lo, 1);
  const at = (v) => clamp((v - lo) / span, 0, 1) * 100;
  const marks = keys.map((k) => {
    const v = shown[k];
    if (v === null || v === undefined) return "";
    const tone = k === "target_temp_high" || (k === "temperature" && c.mode === "cool") ? "cool" : "heat";
    return `<i class="mark ${tone}" style="left:${at(v).toFixed(1)}%"></i>`;
  }).join("");
  const now_ = c.house.average ?? c.house.down;
  const here = now_ === null || now_ === undefined ? "" : `<i class="here" style="left:${at(now_).toFixed(1)}%"></i>`;
  return `<div class="scale"><div class="track">${marks}${here}</div>
    <div class="ends"><span>${fmt(lo)}</span><span>LIMITS</span><span>${fmt(hi)}</span></div></div>`;
}

function setpointRow(key, label, value, can, c, shown, inFlight) {
  const [lo, hi] = c.guardrails;
  const canDown = can && step(shown, key, -1, lo, hi, c.gap) !== null;
  const canUp = can && step(shown, key, 1, lo, hi, c.gap) !== null;
  const tone = key === "target_temp_high" || (key === "temperature" && c.mode === "cool") ? "cool" : "heat";
  return `<div class="setpoint ${tone}">
    <button class="key arrow" data-act="nudge-down" data-arg="${key}" ${canDown ? "" : "disabled"}><b class="tri down"></b></button>
    <div class="sp"><span class="k">${esc(label)}</span><span class="v ${inFlight ? "flying" : ""}">${fmt(value)}</span></div>
    <button class="key arrow" data-act="nudge-up" data-arg="${key}" ${canUp ? "" : "disabled"}><b class="tri up"></b></button></div>`;
}

function renderClimate(el, st, back) {
  const shell = appShell(el, "climate", back);
  const h = st.home;
  lockBadge(shell, h);
  if (!h || !h.climate.available) {
    setText(shell.kicker, "THE THERMOSTAT // HOME ASSISTANT");
    paint(shell.body, box("OFFLINE", `<div class="soon">${h ? "Home Assistant hasn't reported the thermostat yet." : "No Home Assistant token in the panel's settings."}</div>`, "alarm") + (h ? lockBar(h) : ""));
    return;
  }
  const c = h.climate, f = flight.climate, can = h.lock.can_change;
  setText(shell.kicker, `THE THERMOSTAT // ${c.mode_label} // ${c.action_label}`);
  const { setpoints, mode } = climateShown(h);
  const keys = f.mode ? [] : c.targets;
  const house = c.house;
  const acting = c.action === "heating" ? "heat" : c.action === "cooling" ? "cool" : "";

  const now_ = box("HOUSE", `<div class="house">
      <div class="avg"><span class="v">${fmt(house.average ?? house.down)}</span>
        <span class="k">${house.average !== null && house.average !== undefined ? "AVERAGE" : "DOWNSTAIRS"}</span></div>
      <div class="floors">
        <div><span class="k">UPSTAIRS</span><span>${fmt(house.up)}</span></div>
        <div><span class="k">DOWNSTAIRS</span><span>${fmt(house.down)}</span></div>
        <div><span class="k">HUMIDITY</span><span>${house.humidity === null || house.humidity === undefined ? "--" : Math.round(house.humidity) + "%"}</span></div>
      </div></div>
      <div class="acting ${acting}"><i class="led"></i>${esc(c.action_label)}${house.note ? ` <em>// ${esc(house.note)}</em>` : ""}</div>`);

  let controls;
  if (f.mode) controls = `<div class="sp-note">SETTING ${esc(MODE_NAMES[f.mode] || f.mode.toUpperCase())}</div>`;
  else if (!keys.length) controls = `<div class="sp-note">SYSTEM OFF: PICK A MODE</div>`;
  else {
    controls = keys.map((k) => setpointRow(k, TARGET_NAMES[k] || (mode === "cool" ? "COOL TO" : "HEAT TO"), setpoints[k], can, c,
      setpoints, k in f.pending || k in f.sent)).join("");
  }
  const modes = `<div class="modes">${c.modes.map((m) => `<button class="key mode ${m === mode ? "on" : ""}" data-act="mode" data-arg="${m}"
    ${can ? "" : "disabled"}>${MODE_NAMES[m] || m.toUpperCase()}</button>`).join("")}</div>`;

  paint(shell.body, now_ + scale(c, setpoints, keys) + box("SETPOINT", controls + modes, can ? "live" : "") + lockBar(h));
}

function renderLights(el, st, back) {
  const shell = appShell(el, "lights", back);
  const h = st.home;
  lockBadge(shell, h);
  setText(shell.kicker, "HOME ASSISTANT // LIGHTING CONTROL");
  if (!h) {
    paint(shell.body, box("OFFLINE", `<div class="soon">No Home Assistant token in the panel's settings.</div>`, "alarm"));
    return;
  }
  const can = h.lock.can_change;
  let rows;
  if (!h.lights.length) {
    rows = box("NONE", `<div class="soon">No lights in the panel's settings yet (lights.entities).</div>`);
  } else {
    rows = h.lights.slice(0, 5).map((light) => {
      const l = lightShown(light);
      const usable = can && l.available;
      const state_ = !l.known ? "--" : !l.available ? "UNAVAILABLE" : l.on ? (l.pct === null ? "ON" : `ON ${l.pct}%`) : "OFF";
      const fill = l.on ? (l.pct === null ? 1 : l.pct / 100) : 0;
      return `<div class="light ${l.on ? "on" : ""} ${l.available ? "" : "gone"}">
        <div class="top"><span class="name">${esc(l.name)}</span><span class="st">${esc(state_)}</span></div>
        ${bar(fill, "glow")}
        <div class="btns">
          <button class="key step" data-act="light-down" data-arg="${esc(l.entity)}" ${usable && l.on ? "" : "disabled"}>-</button>
          <button class="key step" data-act="light-up" data-arg="${esc(l.entity)}" ${usable ? "" : "disabled"}>+</button>
          <button class="key toggle ${l.on ? "on" : ""}" data-act="light-toggle" data-arg="${esc(l.entity)}" ${usable ? "" : "disabled"}>${l.on ? "ON" : "OFF"}</button>
        </div></div>`;
    }).join("");
    if (h.lights.length > 5) rows += `<div class="foot">+${h.lights.length - 5} MORE IN THE SETTINGS (THE FIRST 5 SHOWN)</div>`;
  }
  paint(shell.body, `<div class="lights">${rows}</div>` + lockBar(h));
}

// Called by panel.js's render(), and after a tap or an answer.
function renderControls() {
  if (!state) return;
  renderClimate(screens.climate, state, backOf("climate"));
  renderLights(screens.lights, state, backOf("lights"));
  for (const k of Object.values(keypads)) {
    if (!k.open) continue;
    const h = hass();
    if (h && h.lock.can_change) closeKeypad(k.name); // opened from Home Assistant meanwhile
    else renderKeypad(k);
  }
}

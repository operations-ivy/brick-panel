// The app screens' contents: WEATHER, BRICK and ALERTS, plus the shared bits
// every screen uses. Each screen is rebuilt only when what it shows changes
// (paint() keeps the last HTML), never during a screen change (panel.js
// skips rendering while one runs), and never animates anything but
// transform/opacity, so the screen changes stay smooth.
"use strict";

const TITLES = { weather: "WEATHER", climate: "CLIMATE", lights: "LIGHTS", brick: "BRICK", alerts: "ALERTS",
  calendar: "CALENDAR", shopping: "SHOPPING" };

// ---- Shared ----

function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function deg(t) {
  return t === null || t === undefined ? "--°" : `${Math.round(t)}°`;
}

function setText(el, text) {
  if (el.textContent !== text) el.textContent = text;
}

// Sets an element's HTML only when it differs from what was set last time
// (comparing against innerHTML wouldn't work: the browser re-serialises it).
const painted = new WeakMap();
function paint(el, html) {
  if (painted.get(el) === html) return false;
  el.innerHTML = html;
  painted.set(el, html);
  return true;
}

function ago(seconds) {
  if (seconds === null || seconds === undefined) return "--";
  if (seconds < 90) return "JUST NOW";
  if (seconds < 5400) return `${Math.round(seconds / 60)} MIN AGO`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)} HR AGO`;
  return `${Math.round(seconds / 86400)} DAYS AGO`;
}

function clockTime(ts, hours24) {
  const d = new Date(ts * 1000);
  let h = d.getHours();
  const m = String(d.getMinutes()).padStart(2, "0");
  if (hours24) return `${String(h).padStart(2, "0")}:${m}`;
  const ampm = h < 12 ? "AM" : "PM";
  h = h % 12 || 12;
  return `${h}:${m} ${ampm}`;
}

function box(tab, body, cls = "") {
  return `<div class="panel-box ${cls}"><span class="tab">${tab}</span><div class="body">${body}</div></div>`;
}

// A bar from 0 to 1, drawn once (scaleX on a static element, never animated).
function bar(fraction, cls = "") {
  const f = Math.max(0, Math.min(1, fraction || 0));
  return `<span class="bar ${cls}"><i style="transform:scaleX(${f.toFixed(3)})"></i></span>`;
}

// The screen's head and an empty body, built once.
function appShell(el, name, back) {
  if (!el.dataset.built) {
    el.style.setProperty("--c", `var(${Scene.COLOURS[name] || "--cyan"})`);
    el.classList.add(`back-${back}`);
    el.innerHTML = `<div class="app-head"><div class="kicker"></div><h1>${TITLES[name]}</h1><div class="badge"></div></div>
      <div class="app-body"></div>`;
    el.dataset.built = "1";
  }
  return { kicker: el.querySelector(".kicker"), badge: el.querySelector(".badge"), body: el.querySelector(".app-body") };
}

function badge(el, text, tone) {
  setText(el, text);
  el.className = `badge ${tone || ""}`;
}

// ---- Weather icons: neon line drawings, 48x48 ----

function wxKind(text) {
  const c = (text || "").toUpperCase();
  if (/THUNDER|STORM/.test(c)) return "storm";
  if (/SNOW|SLEET|ICE|FLURR|WINTRY/.test(c)) return "snow";
  if (/RAIN|DRIZZLE|SHOWER/.test(c)) return "rain";
  if (/FOG|HAZE|MIST|SMOKE/.test(c)) return "fog";
  if (/PARTLY|MOSTLY SUNNY|MOSTLY CLEAR|FEW CLOUDS|SCATTERED/.test(c)) return "partly";
  if (/CLOUD|OVERCAST/.test(c)) return "cloud";
  return "clear";
}

const CLOUD = '<path d="M13 35h23a7.5 7.5 0 0 0 .5-15 11 11 0 0 0-21 2.5A6.3 6.3 0 0 0 13 35z"/>';
function sky(day, small) {
  const s = small ? ' transform="translate(-7 -8) scale(.75)"' : "";
  if (!day) return `<g${s} class="moon"><path d="M29 9a15 15 0 1 0 11 21 12 12 0 0 1-11-21z"/></g>`;
  const rays = [0, 45, 90, 135, 180, 225, 270, 315].map((a) => {
    const r = (a * Math.PI) / 180, c = Math.cos(r), n = Math.sin(r);
    return `M${(24 + 11 * c).toFixed(1)} ${(24 + 11 * n).toFixed(1)}L${(24 + 16 * c).toFixed(1)} ${(24 + 16 * n).toFixed(1)}`;
  }).join("");
  return `<g${s} class="sun"><circle cx="24" cy="24" r="7"/><path d="${rays}"/></g>`;
}

function icon(text, day, cls = "") {
  const kind = wxKind(text);
  const up = '<g transform="translate(0 -6)">' + CLOUD + "</g>";
  const art = {
    clear: sky(day, false),
    partly: sky(day, true) + `<g class="cloud">${CLOUD}</g>`,
    cloud: `<g class="cloud">${CLOUD}</g>`,
    rain: `<g class="cloud">${up}</g><path class="drops" d="M17 35l-3 7M25 35l-3 7M33 35l-3 7"/>`,
    storm: `<g class="cloud">${up}</g><path class="bolt" d="M26 31l-6 8h6l-4 8"/>`,
    snow: `<g class="cloud">${up}</g><path class="flakes" d="M16 37h2M24 41h2M32 37h2M20 44h2M28 44h2"/>`,
    fog: '<path class="fog" d="M9 18h30M6 25h36M9 32h30M12 39h24"/>',
  }[kind];
  return `<svg class="wx-icon wx-${kind} ${cls}" viewBox="0 0 48 48" aria-hidden="true">${art}</svg>`;
}

// ---- WEATHER ----

// "WEDNESDAY NIGHT" -> "WED NIGHT": the forecast's names, to fit a third of the screen.
function shortDay(name) {
  return String(name || "").replace(/\b(MON|TUE|WED|THU|FRI|SAT|SUN)[A-Z]*DAY\b/g, "$1");
}

// The forecast periods' temperatures as one line: the next days' shape at a glance.
function trace(periods) {
  const temps = periods.map((p) => p.temperature).filter((t) => t !== null && t !== undefined);
  if (temps.length < 2) return "";
  const W = 436, H = 64, PAD = 12;
  const lo = Math.min(...temps), hi = Math.max(...temps), span = Math.max(hi - lo, 1);
  const step = (W - 2 * PAD) / (periods.length - 1);
  const pts = periods.map((p, i) => ({ x: PAD + i * step, y: PAD + (H - 2 * PAD) * (1 - ((p.temperature ?? lo) - lo) / span),
    day: p.day, t: p.temperature }));
  const line = pts.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  const dots = pts.map((p) => `<rect class="${p.day ? "day" : "night"}" x="${(p.x - 4).toFixed(1)}" y="${(p.y - 4).toFixed(1)}"
    width="8" height="8"/>`).join("");
  return `<svg class="wx-trace" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">
    <path class="grid" d="M0 ${PAD}H${W}M0 ${H - PAD}H${W}"/><polyline points="${line}"/>${dots}</svg>
    <div class="wx-range"><span>HIGH ${deg(hi)}</span><span>LOW ${deg(lo)}</span></div>`;
}

function renderWeather(el, state, back) {
  const w = state.weather || {};
  const cur = w.current || {};
  const shell = appShell(el, "weather", back);
  setText(shell.kicker, `OUTSIDE // ${String(w.source || "NO SOURCE").toUpperCase()}`);
  const warnings = (state.alerts && state.alerts.weather) || [];
  badge(shell.badge, warnings.length ? `${warnings.length} WARNING${warnings.length > 1 ? "S" : ""}` : "",
    warnings.length ? "red" : "");

  const night = isNight();
  const meta = [
    cur.humidity != null ? `${Math.round(cur.humidity)}% HUMIDITY` : null,
    cur.wind_mph != null ? `WIND ${cur.wind_from || ""} ${Math.round(cur.wind_mph)} MPH`.replace("  ", " ") : null,
  ].filter(Boolean);
  const now = box("NOW", `<div class="wx-now">${icon(cur.condition, !night, "big-icon")}
    <div class="big">${deg(cur.temperature)}</div>
    <div class="what"><div class="cond">${esc(cur.condition || w.error || "NO SIGNAL")}</div>
      ${meta.map((m) => `<div class="meta">${esc(m)}</div>`).join("")}</div></div>`);

  const warn = warnings.length ? box("WARNINGS", warnings.slice(0, 2).map((a) => `<div class="wx-warn">
    <b>${esc(a.event)}</b><span>${a.ends ? "UNTIL " + esc(clockTime(a.ends, state.clock.hours === 24)) : ""}</span></div>`).join(""),
  "alarm") : "";

  // Two rows of three; one row when warnings take the room.
  const periods = (w.periods || []).slice(0, warnings.length ? 3 : 6);
  const cards = periods.map((p) => `<div class="wx-period ${p.day ? "day" : "night"}">
      <div class="name">${esc(shortDay(p.name))}</div>
      <div class="mid"><span class="t">${deg(p.temperature)}</span>${icon(p.forecast, p.day)}</div>
      <div class="f">${esc(p.forecast)}</div>
      <div class="r">${p.rain ? `${bar(p.rain / 100, "wet")}<span>${p.rain}%</span>` : "<span class=\"dry\">DRY</span>"}</div></div>`).join("");
  const foot = [w.age != null ? `UPDATED ${ago(w.age)}` : "", w.error].filter(Boolean).join(" // ");

  paint(shell.body, `${now}${warn}<div class="wx-ahead">${trace((w.periods || []).slice(0, 6))}</div>
    <div class="wx-periods">${cards}</div><div class="foot">${esc(foot)}</div>`);
}

// ---- BRICK: brick9000's board, on the wall ----

const TONE = { ok: "ok", active: "ok", warn: "warn", unknown: "dim", fail: "bad" };
const OVERALL = { ok: "ALL GOOD", active: "WORKING", warn: "WARN", unknown: "UNKNOWN", fail: "FAIL" };

function vital(label, value, max, warn) {
  const text = value === null || value === undefined ? "--" : `${Math.round(value)}${label === "TEMP" ? "°" : "%"}`;
  return `<div class="vital ${warn ? "warn" : ""}"><span class="k">${label}</span>${bar((value || 0) / max)}<span class="v">${text}</span></div>`;
}

function renderBrick(el, state, back) {
  const b = state.brick;
  const shell = appShell(el, "brick", back);
  setText(shell.kicker, "HOMELAB // BRICK9000'S BOARD");
  const age = (state.feeds || {}).board;
  if (!b) {
    badge(shell.badge, "NO SIGNAL", "dim");
    paint(shell.body, box("OFFLINE", `<div class="soon">The board isn't answering${age != null ? `; last seen ${esc(ago(age).toLowerCase())}` : ""}.
      <br><br><b>// STATUS.BRICK.NOZDORMU.CLOUD</b></div>`, "alarm"));
    return;
  }
  badge(shell.badge, OVERALL[b.overall] || "UNKNOWN", TONE[b.overall]);

  const nodes = b.vitals.map((v) => `<div class="node">
      <div class="name">${esc((v.node || "?").toUpperCase())}</div>
      ${vital("CPU", v.cpu, 100, v.cpu > 85)}${vital("MEM", v.mem, 100, v.mem > 90)}
      ${vital("TEMP", v.temp, 85, v.temp_warn)}${vital("DISK", v.disk, 100, v.disk > 85)}</div>`).join("");

  const groups = b.groups.map((g) => {
    const p = g.problems[0];
    const detail = p ? `${p.name} ${p.detail}`.toUpperCase() : `${g.ok}/${g.total} OK`;
    return `<div class="row ${TONE[g.state]}"><i class="led"></i><span class="k">${esc(g.name)}</span>
      <span class="v">${esc(detail)}${g.problems.length > 1 ? ` +${g.problems.length - 1}` : ""}</span></div>`;
  }).join("");

  const builds = b.recent.slice(0, 4).map((r) => `<div class="row ${TONE[r.state] || "dim"}"><i class="led"></i>
      <span class="k">${esc((r.job || "?").toUpperCase())}<em>#${esc(r.number)}</em></span><span class="v">${esc((r.what || "").toUpperCase())}</span></div>`).join("");
  const shipped = b.shipped.map((s) => `${esc(s.name)} ${esc(s.version)}`).join(" · ");
  const net = b.internet === false ? "INTERNET DOWN // " : "";

  paint(shell.body, box("NODES", `<div class="nodes">${nodes || "<div class=\"soon\">NO VITALS</div>"}</div>`) +
    box("SYSTEMS", `<div class="rows">${groups}</div>`, b.overall === "fail" ? "alarm" : "") +
    box("BUILDS", `<div class="rows">${builds || "<div class=\"soon\">NO BUILDS</div>"}</div>`) +
    `<div class="foot">${net}${shipped ? "SHIPPED " + shipped.toUpperCase() + " // " : ""}${esc(ago(age))}</div>`);
}

// ---- ALERTS: the alert condition ----

const CONDITION_TONE = { RED: "bad", YELLOW: "warn", GREEN: "ok", UNKNOWN: "dim" };
const SEVERITY_TONE = { critical: "bad", warning: "warn", info: "dim" };
const WEATHER_TONE = { Extreme: "bad", Severe: "warn" };

function feedTone(severity) {
  return severity >= 3 ? "bad" : severity === 2 ? "warn" : "ok";
}

function lines(items, empty, max) {
  if (!items.length) return `<div class="row dim"><i class="led"></i><span class="v">${esc(empty)}</span></div>`;
  const shown = items.length > max ? items.slice(0, max - 1) : items;
  let html = shown.map(([tone, text, note]) => `<div class="row ${tone}"><i class="led"></i>
    <span class="v">${esc(text)}</span>${note ? `<span class="n">${esc(note)}</span>` : ""}</div>`).join("");
  if (items.length > max) html += `<div class="row dim"><i class="led"></i><span class="v">+${items.length - shown.length} MORE</span></div>`;
  return html;
}

function renderAlerts(el, state, back) {
  const a = state.alerts || { condition: "UNKNOWN" };
  const feeds = state.feeds || {};
  const shell = appShell(el, "alerts", back);
  setText(shell.kicker, "BRICK//1982 // ALERT CONDITION");
  badge(shell.badge, a.count ? `${a.count} ACTIVE` : "", a.count ? CONDITION_TONE[a.condition] : "");

  const banner = `<div class="condition ${CONDITION_TONE[a.condition]}"><span class="k">CONDITION</span>
    <span class="v">${esc(a.condition)}</span></div>`;

  const infra = a.infra === null || a.infra === undefined
    ? lines([["bad", "PROMETHEUS OFFLINE", ""]], "", 1)
    : lines(a.infra.map((x) => [SEVERITY_TONE[x.severity], x.text, x.severity.toUpperCase()]), "ALL SYSTEMS NOMINAL", 5);

  const weather = a.weather === null || a.weather === undefined
    ? lines([], "NO WARNINGS SOURCE", 1)
    : lines(a.weather.map((x) => [WEATHER_TONE[x.severity] || "dim", x.event,
      x.ends ? "TO " + clockTime(x.ends, state.clock.hours === 24) : ""]), "NO WARNINGS", 3);

  let watch;
  if (!a.watch) {
    watch = lines([["bad", "OVERWATCH OFFLINE", ""]], "", 1);
  } else {
    const items = a.watch.feeds.map((f) => [feedTone(f.severity), `${f.name} ${f.word}`, f.severity >= 2 ? f.line : ""]);
    for (const r of a.watch.recent) items.push([r.live ? "bad" : "warn", r.text, ago(state.now - r.at)]);
    watch = lines(items, "NO FEEDS", 5);
  }

  const src = [["PROMETHEUS", feeds.prometheus], ["OVERWATCH", feeds.overwatch]]
    .filter(([name]) => name.toLowerCase() in feeds).map(([name, age]) => `${name} ${ago(age)}`).join(" // ");

  paint(shell.body, banner +
    box("INFRASTRUCTURE", `<div class="rows">${infra}</div>`) +
    box("WEATHER SERVICE", `<div class="rows">${weather}</div>`) +
    box("OVERWATCH", `<div class="rows">${watch}</div>`) +
    `<div class="foot">${esc(src)}</div>`);
}

// What the ALERTS billboard on Home says.
function alertsBillboard(state) {
  const a = state.alerts;
  if (!a || a.condition === "UNKNOWN") return { text: "NO SIGNAL", lit: false };
  if (!a.count) return { text: "ALL CLEAR", lit: false };
  return { text: `${a.count} ACTIVE`, lit: a.condition !== "GREEN" };
}

// Night by the clock until the panel knows the sun's times (night mode, PR 4).
function isNight() {
  const h = new Date().getHours();
  return h < 7 || h >= 18;
}

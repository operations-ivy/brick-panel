// Home's surprises, now and then, each spelling one of three names (the
// server's BRICK_PANEL_NAMES; never in this file): a plane towing a banner
// across the sky, the city's windows drifting together into letters, and a
// small neon sign on a tall building in the far skyline, dark until its turn,
// that sputters on for a few seconds. One at a time, minutes apart (so each name
// shows about as often as the others), only on Home, only by day or awake.
// The BRICK sign always says BRICK. Like everything on the page, they animate
// transform and opacity only.
"use strict";

const Pizazz = (() => {
  const EVERY_MS = [150000, 330000]; // between surprises
  // A 5x7 pixel font: each letter seven rows of five.
  const FONT = {
    A: ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    B: ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
    C: ["01110", "10001", "10000", "10000", "10000", "10001", "01110"],
    D: ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    E: ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
    F: ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
    G: ["01110", "10001", "10000", "10111", "10001", "10001", "01111"],
    H: ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
    I: ["01110", "00100", "00100", "00100", "00100", "00100", "01110"],
    J: ["00111", "00010", "00010", "00010", "00010", "10010", "01100"],
    K: ["10001", "10010", "10100", "11000", "10100", "10010", "10001"],
    L: ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    M: ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    N: ["10001", "10001", "11001", "10101", "10011", "10001", "10001"],
    O: ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    P: ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    Q: ["01110", "10001", "10001", "10001", "10101", "10010", "01101"],
    R: ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    S: ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
    T: ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    U: ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    V: ["10001", "10001", "10001", "10001", "10001", "01010", "00100"],
    W: ["10001", "10001", "10001", "10101", "10101", "10101", "01010"],
    X: ["10001", "10001", "01010", "00100", "01010", "10001", "10001"],
    Y: ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    Z: ["11111", "00001", "00010", "00100", "01000", "10000", "11111"],
  };

  let home = null, running = null, timer = null, order = [];
  let built = "", planeEl = null, lightsEl = null, skylineEl = null, dots = [];

  const names = () => (state && state.names && state.names.length === 3 ? state.names : null);

  function layer(cls) {
    const el = document.createElement("div");
    el.className = `pz ${cls}`;
    home.appendChild(el);
    return el;
  }

  // The plane and the letters are built (and painted) once, when the names
  // arrive, and wait out of sight: starting one only animates it, so its
  // first frame is as quick as the rest.
  function prepare() {
    const n = names();
    if (!n || !home || built === n.join()) return;
    built = n.join();
    for (const el of [planeEl, lightsEl, skylineEl]) if (el) el.remove();
    planeEl = layer("pz-plane");
    planeEl.innerHTML = `<div class="banner"><span>${esc(n[0])}</span></div><i class="line"></i>
      <svg class="craft" viewBox="0 0 40 16" width="100" height="40" aria-hidden="true">
        <path d="M2 7h26l8 2-8 2H6z" /><path d="M14 7l5-6h3l-3 6zM14 11l5 4h3l-3-4z" class="wing" />
        <path d="M2 4h3l2 3H2z" class="wing" /><rect x="29" y="7" width="3" height="2" class="glass" />
        <rect x="2.5" y="2.6" width="1.4" height="1.4" class="beacon" /></svg>`;
    const name = n[1];
    const cols = name.length * 6 - 1;
    const pitch = Math.min(12, Math.floor(452 / cols));
    const left = Math.round((480 - cols * pitch) / 2), top = 648;
    dots = [];
    [...name].forEach((ch, i) => (FONT[ch] || []).forEach((row, y) => [...row].forEach((bit, x) => {
      if (bit === "1") dots.push([left + (i * 6 + x) * pitch, top + y * 13]);
    })));
    lightsEl = layer("pz-lights");
    // A veil dims the rest of the city's lights while the letters hold.
    lightsEl.innerHTML = `<b class="veil"></b>` + dots.map(([x, y]) => `<i style="left:${x}px;top:${y}px"></i>`).join("");
    // The skyline sign: the dark tube always there, the lit one over it
    // only while it's on.
    const letters = [...n[2]].map((c) => `<span>${c}</span>`).join("");
    skylineEl = layer("pz-skyline");
    skylineEl.innerHTML = `<div class="tube off">${letters}</div><div class="tube on">${letters}</div>`;
  }

  // 1. A plane across the sky, a banner on a line behind it.
  function plane() {
    const width = planeEl.offsetWidth;
    const fly = planeEl.animate([{ transform: `translate3d(${-width - 20}px,0,0)` }, { transform: "translate3d(500px,0,0)" }],
      { duration: 17000, easing: "linear" });
    const flutter = planeEl.querySelector(".banner").animate(
      [{ transform: "skewY(0deg)" }, { transform: "skewY(-2deg)" }, { transform: "skewY(1deg)" }, { transform: "skewY(0deg)" }],
      { duration: 1400, iterations: Infinity });
    return { anims: [fly, flutter], done: fly.finished };
  }

  // 2. The city's windows drift together into letters, hold, drift apart.
  function lights() {
    const dim = [{ opacity: 0 }, { opacity: 0.8, offset: 0.28 }, { opacity: 0.8, offset: 0.74 }, { opacity: 0 }];
    const anims = [lightsEl.querySelector(".veil").animate(dim, { duration: 8000 }),
      home.querySelector(".windows").animate(dim.map((k) => ({ ...k, opacity: 1 - k.opacity })), { duration: 8000 })];
    lightsEl.querySelectorAll("i").forEach((d, i) => {
      const [x, y] = dots[i];
      const from = `translate3d(${Math.round(20 + Math.random() * 440 - x)}px,${Math.round(500 + Math.random() * 280 - y)}px,0)`;
      const at = "translate3d(0,0,0)";
      anims.push(d.animate([
        { transform: from, opacity: 0 },
        { transform: from, opacity: 0.9, offset: 0.08 },
        { transform: at, opacity: 1, offset: 0.3 },
        { transform: at, opacity: 1, offset: 0.72 },
        { transform: from, opacity: 0.9, offset: 0.92 },
        { transform: from, opacity: 0 },
      ], { duration: 8000, easing: "cubic-bezier(.45,0,.25,1)" }));
    });
    return { anims, done: anims[0].finished };
  }

  // 3. The skyline sign sputters on, glows a while, and goes dark.
  function skyline() {
    const on = skylineEl.querySelector(".on");
    const sputter = (lit) => on.animate(lit
      ? [{ opacity: 0 }, { opacity: 0.7, offset: 0.25 }, { opacity: 0.1, offset: 0.4 }, { opacity: 1, offset: 0.55 }, { opacity: 0.4, offset: 0.7 }, { opacity: 1 }]
      : [{ opacity: 1 }, { opacity: 0.2, offset: 0.2 }, { opacity: 0.9, offset: 0.35 }, { opacity: 0.1, offset: 0.6 }, { opacity: 0.6, offset: 0.7 }, { opacity: 0 }],
    { duration: 900, easing: "steps(6)", fill: "forwards" });
    const anims = [];
    const step = (a) => { anims.push(a); return a.finished; };
    const run = { anims, done: null };
    run.done = (async () => {
      await step(sputter(true));
      await new Promise((r) => setTimeout(r, 6000));
      if (running !== run) return;
      await step(sputter(false));
    })();
    return run;
  }

  const SHOWS = [plane, lights, skyline];

  function play(which) {
    const n = names();
    if (!n || running || busy || dark || current !== "home") return false;
    prepare();
    running = SHOWS[which](n[which]);
    Sfx.play(["surprise_plane", "surprise_lights", "surprise_sign"][which]);
    const run = running;
    run.done.catch(() => {}).finally(() => { if (running === run) clear(); });
    return true;
  }

  function clear() {
    const run = running;
    running = null;
    if (!run) return;
    for (const a of run.anims) a.cancel(); // back out of sight (the skyline sign: dark)
  }

  // Every few minutes, the next of the three (in a shuffled order, so all
  // three come round).
  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(() => {
      if (!order.length) order = [0, 1, 2].sort(() => Math.random() - 0.5);
      if (play(order[0])) order.shift();
      schedule();
    }, EVERY_MS[0] + Math.random() * (EVERY_MS[1] - EVERY_MS[0]));
  }

  function start(homeEl) {
    home = homeEl;
    schedule();
  }

  // Until the one playing is over (the bench times it).
  function wait() {
    return running ? running.done.catch(() => {}).then(() => new Promise((r) => setTimeout(r, 50))) : Promise.resolve();
  }

  // Leaving Home, or going dark: whatever's on stops (Home is covered).
  return { start, prepare, play, wait, stop: clear };
})();

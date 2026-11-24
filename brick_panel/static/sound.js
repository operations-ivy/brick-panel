// The panel's sounds, all made here with Web Audio (no audio files): short
// neon blips and chimes. Whether one plays is the server's choice
// (state.sound, from SETTINGS' checkboxes and quiet hours; sound.py), and
// how loud is its level under brick1982's ALSA cap. SETTINGS (a tap on the
// STRAYLIGHT logo) and the mute button (on every screen) are drawn here too.
"use strict";

const Sfx = (() => {
  let ctx = null, out = null, hushed = false;

  function audio() {
    if (!ctx) {
      ctx = new AudioContext();
      out = ctx.createGain();
      out.connect(ctx.destination);
    }
    if (ctx.state === "suspended") ctx.resume();
    return ctx;
  }

  // One note: an oscillator through its own envelope, optionally gliding.
  function note(t, { freq, dur, type = "square", vol = 0.1, glide = null, attack = 0.004 }) {
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.type = type;
    o.frequency.setValueAtTime(freq, t);
    if (glide) o.frequency.exponentialRampToValueAtTime(glide, t + dur);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(vol, t + attack);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g).connect(out);
    o.start(t);
    o.stop(t + dur + 0.02);
  }

  // Each sound: what it plays, starting at t.
  const SOUNDS = {
    tap: (t) => note(t, { freq: 1800, dur: 0.025, vol: 0.06 }),
    screen: (t) => {
      note(t, { freq: 320, dur: 0.14, type: "triangle", vol: 0.12, glide: 960 });
      note(t + 0.02, { freq: 640, dur: 0.12, type: "sine", vol: 0.05, glide: 1900 });
    },
    pin_key: (t) => note(t, { freq: 1250, dur: 0.04, vol: 0.07 }),
    pin_ok: (t) => [660, 880, 1320].forEach((f, i) => note(t + i * 0.07, { freq: f, dur: 0.09, type: "triangle", vol: 0.14 })),
    pin_bad: (t) => {
      note(t, { freq: 220, dur: 0.14, type: "sawtooth", vol: 0.08 });
      note(t + 0.16, { freq: 165, dur: 0.22, type: "sawtooth", vol: 0.08 });
    },
    alert: (t) => [880, 660, 880, 660].forEach((f, i) => note(t + i * 0.17, { freq: f, dur: 0.15, type: "triangle", vol: 0.16 })),
    // The plane: a far-off propeller drone, rising and falling as it passes.
    surprise_plane: (t) => {
      const o = ctx.createOscillator(), lfo = ctx.createOscillator(), depth = ctx.createGain(), g = ctx.createGain();
      o.type = "sawtooth";
      o.frequency.value = 95;
      lfo.frequency.value = 22;
      depth.gain.value = 0.02;
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(0.03, t + 1.2);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 3);
      lfo.connect(depth).connect(g.gain);
      o.connect(g).connect(out);
      for (const x of [o, lfo]) { x.start(t); x.stop(t + 3.05); }
    },
    // The windows: a sparkle of high pings as the letters gather.
    surprise_lights: (t) => {
      for (let i = 0; i < 8; i++) {
        note(t + i * 0.11 + Math.random() * 0.04, { freq: 1400 + Math.random() * 1600, dur: 0.12, type: "sine", vol: 0.06 });
      }
    },
    // The skyline sign: a neon tube's buzz, sputtering on.
    surprise_sign: (t) => {
      const o = ctx.createOscillator(), f = ctx.createBiquadFilter(), g = ctx.createGain();
      o.type = "sawtooth";
      o.frequency.value = 120;
      f.type = "lowpass";
      f.frequency.value = 700;
      [0, 0.05, 0.02, 0.05, 0.01, 0.05].forEach((v, i) => g.gain.setValueAtTime(Math.max(v, 0.0001), t + i * 0.12));
      g.gain.exponentialRampToValueAtTime(0.0001, t + 1.1);
      o.connect(f).connect(g).connect(out);
      o.start(t);
      o.stop(t + 1.15);
    },
  };

  // Whether a sound may play now: not muted (quiet hours, or the mute
  // button), and its checkbox ticked.
  function allowed(name) {
    const s = state && state.sound;
    return Boolean(s && !hushed && !s.muted && s.events[name]);
  }

  // preview: SETTINGS playing a sound as it's ticked, whatever the rules.
  function play(name, preview = false) {
    if (!SOUNDS[name] || (!preview && !allowed(name))) return;
    try {
      const c = audio();
      out.gain.value = (state && state.sound ? state.sound.gain : 1) * 0.8;
      SOUNDS[name](c.currentTime + 0.01);
    } catch (e) { /* no audio device: stay silent */ }
  }

  // Quiet while the bench runs (it plays the surprises and changes screens).
  function hush(on) { hushed = on; }

  return { play, hush, EVENTS: Object.keys(SOUNDS) };
})();

// ---- SETTINGS ----

const SOUND_LABELS = {
  tap: "TAP", screen: "SCREEN CHANGE", pin_key: "CODE KEYS", pin_ok: "CODE ACCEPTED", pin_bad: "WRONG CODE",
  alert: "NEW ALERT", surprise_plane: "SURPRISE: PLANE", surprise_lights: "SURPRISE: WINDOWS",
  surprise_sign: "SURPRISE: SKYLINE SIGN",
};

function settingsRow(act, arg, on, label) {
  return `<button class="set-item ${on ? "on" : ""}" data-act="${act}" data-arg="${arg}"><i class="check"></i><span>${label}</span></button>`;
}

function renderSettings(el, st, back) {
  const shell = appShell(el, "settings", back);
  setText(shell.kicker, "STRAYLIGHT // PANEL SETTINGS");
  const s = st.sound;
  if (!s) {
    badge(shell.badge, "OFF", "dim");
    paint(shell.body, `<div class="soon">No sound on this panel.</div>`);
    return;
  }
  badge(shell.badge, s.muted ? "MUTED" : "", s.muted ? "warn" : "");
  const level = ["low", "medium"].map((l) =>
    `<button class="key mode ${s.level === l ? "on" : ""}" data-act="sound-level" data-arg="${l}">${l.toUpperCase()}</button>`).join("");
  const sounds = Sfx.EVENTS.map((e) => settingsRow("sound-event", e, s.events[e], SOUND_LABELS[e])).join("");
  const quiet = s.quiet_window
    ? `<div class="set-note">MUTED ${esc(s.quiet_window)}. THE SPEAKER BUTTON, BOTTOM LEFT ON EVERY SCREEN, FLIPS IT.</div>`
    : "";
  paint(shell.body, `<div class="set-head">VOLUME</div><div class="set-level">${level}</div>
    <div class="set-head">SOUNDS</div><div class="set-list">${sounds}</div>${quiet}`);
}

// A change shows at once, then the server's answer (the saved choices) wins.
async function changeSound(body, apply) {
  if (!state || !state.sound) return;
  apply(state.sound);
  renderSettings(screens.settings, state, backOf("settings"));
  const answer = await post("/api/sound", body);
  if (answer && answer.sound) state.sound = answer.sound;
  renderSettings(screens.settings, state, backOf("settings"));
}

Object.assign(ACTIONS, {
  "sound-event": (event) => {
    const on = !state.sound.events[event];
    changeSound({ event, on }, (s) => { s.events[event] = on; });
    if (on) Sfx.play(event, true);
  },
  "sound-level": (level) => {
    changeSound({ level }, (s) => { s.level = level; s.gain = level === "low" ? 0.74 : 1; });
    setTimeout(() => Sfx.play("pin_ok", true), 50);
  },
});

// ---- The mute button, on every screen, no code needed ----

const muteEl = document.getElementById("mute");

function renderMute() {
  const s = state && state.sound;
  muteEl.hidden = !s;
  if (!s) return;
  muteEl.classList.toggle("muted", s.muted);
  muteEl.setAttribute("aria-label", s.muted ? "Unmute" : "Mute");
}

async function toggleMute() {
  if (!state || !state.sound) return;
  state.sound.muted = !state.sound.muted; // at once; the server's answer wins
  renderMute();
  const answer = await post("/api/mute", {});
  if (answer && answer.sound) state.sound = answer.sound;
  renderMute();
  renderSettings(screens.settings, state, backOf("settings"));
  if (!state.sound.muted) Sfx.play("pin_ok");
}

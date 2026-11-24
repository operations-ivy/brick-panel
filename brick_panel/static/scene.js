// Home's rainy city, built once at load. The skyline is painted into a canvas
// one time; everything that moves afterwards (rain, stars, windows, the car)
// is a static layer animated by CSS transform/opacity on the compositor, so
// the main thread draws nothing per frame and screen changes stay smooth.
"use strict";

const Scene = (() => {
  const W = 480, CITY_TOP = 370, CITY_H = 430;

  // A seeded random, so the skyline is the same city every load.
  function rng(seed) {
    return () => {
      seed = (seed * 1664525 + 1013904223) >>> 0;
      return seed / 4294967296;
    };
  }

  // Rooftops the billboards stand on (screen coordinates), and the tower
  // that carries the BRICK sign.
  const NEAR = [
    { x: 0, w: 142, roof: 568 },
    { x: 142, w: 140, roof: 610 },
    { x: 282, w: 142, roof: 582 },
    { x: 424, w: 56, roof: 436 },
  ];
  // Each billboard stands RIG px above its roof: a catwalk under it, two
  // braced girders down to the roof, and lamps over its top edge.
  const BB_W = 124, BB_H = 76, RIG = 30;
  const BILLBOARDS = [
    { x: 10, top: 568 - BB_H - RIG, roof: 568 },
    { x: 150, top: 610 - BB_H - RIG, roof: 610 },
    { x: 290, top: 582 - BB_H - RIG, roof: 582 },
  ];
  // Which rooftops the billboards take, by how many there are.
  const SLOTS = { 1: [1], 2: [0, 2], 3: [0, 1, 2] };
  const COLOURS = { alerts: "--red", calendar: "--cyan", shopping: "--green", weather: "--sodium",
    climate: "--rose", lights: "--amber", brick: "--violet" };

  function paintCity(canvas, rigs) {
    const g = canvas.getContext("2d", { alpha: true });
    const r = rng(1982);
    g.clearRect(0, 0, W, CITY_H);

    // A sodium glow low in the sky behind the city.
    const haze = g.createLinearGradient(0, 0, 0, CITY_H);
    haze.addColorStop(0, "rgba(255,42,109,0)");
    haze.addColorStop(0.55, "rgba(157,78,221,0.10)");
    haze.addColorStop(1, "rgba(255,159,28,0.16)");
    g.fillStyle = haze;
    g.fillRect(0, 0, W, CITY_H);

    const layer = (fill, minH, maxH, minW, maxW, windowChance, windowColour) => {
      let x = -10;
      while (x < W) {
        const w = minW + Math.floor(r() * (maxW - minW));
        const h = minH + Math.floor(r() * (maxH - minH));
        const top = CITY_H - h;
        g.fillStyle = fill;
        g.fillRect(x, top, w, h);
        if (r() < 0.35) g.fillRect(x + w / 2 - 1, top - 14 - r() * 18, 2, 18); // antenna
        for (let wy = top + 8; wy < CITY_H - 6; wy += 11) {
          for (let wx = x + 5; wx < x + w - 6; wx += 9) {
            if (r() < windowChance) {
              g.fillStyle = windowColour(r());
              g.fillRect(wx, wy, 4, 5);
            }
          }
        }
        x += w + Math.floor(r() * 6);
      }
    };
    layer("#161340", 200, 330, 36, 70, 0.10, (v) => (v < 0.5 ? "rgba(0,234,255,0.30)" : "rgba(157,78,221,0.35)"));
    layer("#0e0b2a", 120, 250, 30, 60, 0.16, (v) => (v < 0.7 ? "rgba(255,179,0,0.55)" : "rgba(0,234,255,0.45)"));

    // The near row: fixed, so the billboards and the sign stand on them.
    for (const b of NEAR) {
      const top = b.roof - CITY_TOP;
      g.fillStyle = "#05040c";
      g.fillRect(b.x, top, b.w, CITY_H - top);
      g.fillStyle = "#1b1838";
      g.fillRect(b.x, top, b.w, 2); // roof edge
      for (let wy = top + 34; wy < CITY_H - 8; wy += 13) {
        for (let wx = b.x + 8; wx < b.x + b.w - 8; wx += 12) {
          if (r() < 0.22) {
            g.fillStyle = r() < 0.8 ? "rgba(255,159,28,0.75)" : "rgba(255,42,109,0.7)";
            g.fillRect(wx, wy, 5, 6);
          }
        }
      }
    }
    paintRigs(g, rigs);
  }

  // The billboards' steelwork, painted once with the city (the signs
  // themselves are buttons over it).
  function paintRigs(g, rigs) {
    const steel = "#2a2552", lit = "#463f80", dark = "#120f2c";
    for (const b of rigs) {
      const x = b.x, bottom = b.top + BB_H - CITY_TOP, roof = b.roof - CITY_TOP, top = b.top - CITY_TOP;
      // Girders: two posts, each a dark core with a lit edge.
      for (const px of [x + 20, x + BB_W - 26]) {
        g.fillStyle = steel;
        g.fillRect(px, bottom, 6, roof - bottom);
        g.fillStyle = lit;
        g.fillRect(px, bottom, 1, roof - bottom);
        g.fillStyle = dark;
        g.fillRect(px - 3, roof - 3, 12, 3); // the foot plate
      }
      // X-bracing between them, below the catwalk.
      const l = x + 26, r = x + BB_W - 26, y0 = bottom + 10, y1 = roof - 2;
      g.strokeStyle = steel;
      g.lineWidth = 2;
      g.beginPath();
      g.moveTo(l, y0); g.lineTo(r, y1);
      g.moveTo(r, y0); g.lineTo(l, y1);
      g.stroke();
      // The catwalk: a deck wider than the sign, a railing on posts.
      g.fillStyle = steel;
      g.fillRect(x - 6, bottom + 6, BB_W + 12, 3);
      g.fillStyle = lit;
      g.fillRect(x - 6, bottom + 6, BB_W + 12, 1);
      g.fillStyle = dark;
      for (let rx = x - 4; rx <= x + BB_W + 4; rx += 12) g.fillRect(rx, bottom + 9, 1, 4);
      // Lamps on arms over the top edge, hoods pointing down at the face.
      for (const lx of [x + 28, x + BB_W - 34]) {
        g.fillStyle = steel;
        g.fillRect(lx + 2, top - 10, 2, 12); // the arm
        g.fillStyle = lit;
        g.fillRect(lx - 2, top - 13, 10, 4); // the hood
        g.fillStyle = "rgba(255,240,200,0.9)";
        g.fillRect(lx - 1, top - 9, 8, 1); // the bulb's line
      }
    }
    // A parapet along the near roofs, so the signs have ground to stand on.
    for (const b of NEAR) {
      const t = b.roof - CITY_TOP;
      g.fillStyle = "#2c2858";
      g.fillRect(b.x, t, b.w, 3);
      g.fillStyle = "#3d3878";
      g.fillRect(b.x, t, b.w, 1);
      g.fillStyle = "#14112f";
      for (let px = b.x + 4; px < b.x + b.w - 2; px += 16) g.fillRect(px, t + 3, 3, 5);
    }
  }

  // A few windows that flicker on their own (CSS opacity, stepped).
  function addWindows(el) {
    const r = rng(7);
    let html = "";
    for (let i = 0; i < 14; i++) {
      const b = NEAR[i % 3];
      const x = b.x + 10 + Math.floor(r() * (b.w - 24) / 12) * 12;
      const y = b.roof + 40 + Math.floor(r() * 12) * 13;
      html += `<i style="left:${x}px;top:${y}px;--d:${7 + r() * 9}s;--delay:${-r() * 9}s"></i>`;
    }
    el.innerHTML = html;
  }

  function tile(w, h, draw) {
    const c = document.createElement("canvas");
    c.width = w; c.height = h;
    draw(c.getContext("2d"), rng(w * 31 + h));
    return `url(${c.toDataURL("image/png")})`;
  }

  // The Presto's rain: single green glyphs falling, each dragging the glyph
  // it was a moment ago one line behind it, darker (presto's fx.GlyphDrops),
  // from the Presto's own glyph set. Painted once into a tile that wraps top
  // to bottom; the compositor slides it down.
  const GLYPHS = "0123456789ABCDEF<>=+*:;#%$&@";
  function glyphTile(count, size, head, trail) {
    return tile(480, 400, (g, r) => {
      g.font = `${size}px VT323, monospace`;
      g.textBaseline = "top";
      const line = Math.round(size * 0.85);
      for (let i = 0; i < count; i++) {
        const x = Math.floor(r() * 470), y = Math.floor(r() * 400);
        const a = GLYPHS[Math.floor(r() * GLYPHS.length)], b = GLYPHS[Math.floor(r() * GLYPHS.length)];
        for (const dy of [0, -400, 400]) { // wrapped, so the loop is seamless
          g.fillStyle = trail;
          g.fillText(b, x, y - line + dy);
          g.fillStyle = head;
          g.fillText(a, x, y + dy);
        }
      }
    });
  }

  // Snow: pale flakes, a few bigger than the rest, wrapped like the rain.
  function snowTile(count, big) {
    return tile(480, 400, (g, r) => {
      for (let i = 0; i < count; i++) {
        const x = Math.floor(r() * 478), y = Math.floor(r() * 400);
        const s = r() < 0.25 ? big : big - 1;
        g.fillStyle = r() < 0.2 ? "#bdefff" : "#e8f6ff";
        g.globalAlpha = 0.55 + r() * 0.45;
        for (const dy of [0, -400, 400]) g.fillRect(x, y + dy, s, s);
      }
    });
  }

  function starTile() {
    return tile(480, 420, (g, r) => {
      for (let i = 0; i < 90; i++) {
        g.fillStyle = r() < 0.15 ? "#00eaff" : "#dff6ff";
        g.globalAlpha = 0.25 + r() * 0.6;
        g.fillRect(Math.floor(r() * 480), Math.floor(r() * 400), r() < 0.1 ? 2 : 1, r() < 0.1 ? 2 : 1);
      }
    });
  }

  function staticTile() {
    return tile(240, 240, (g, r) => {
      const img = g.createImageData(240, 240);
      for (let i = 0; i < img.data.length; i += 4) {
        const v = Math.floor(r() * 255);
        img.data[i] = img.data[i + 1] = img.data[i + 2] = v;
        img.data[i + 3] = 255;
      }
      g.putImageData(img, 0, 0);
    });
  }

  // A slight flicker now and then: one of three patterns, its own pace and
  // start, picked at random so no two signs flicker together.
  function flicker() {
    return `--fa:neon-${"abc"[Math.floor(Math.random() * 3)]};--fd:${(7 + Math.random() * 9).toFixed(1)}s;--fdel:-${(Math.random() * 16).toFixed(1)}s`;
  }

  function face(name) {
    return `<i class="tube"></i><span class="name">${name.toUpperCase()}</span><span class="val">--</span>`;
  }

  // The rooftop billboards, and the one hanging from the top edge on chains.
  function billboards(el, roof, hanging) {
    const slots = SLOTS[roof.length] || [];
    let html = roof.map((name, i) => {
      const b = BILLBOARDS[slots[i]];
      return `<button class="billboard ${name}" data-open="${name}" style="left:${b.x}px;top:${b.top}px;--c:var(${COLOURS[name] || "--cyan"});${flicker()}">
        ${face(name)}<i class="spill" style="top:${b.roof - b.top - 4}px"></i></button>`;
    }).join("");
    if (hanging) {
      html += `<button class="billboard hanging ${hanging}" data-open="${hanging}" style="--c:var(${COLOURS[hanging] || "--cyan"});${flicker()}">
        <i class="chain l"></i><i class="chain r"></i>${face(hanging)}</button>`;
    }
    el.innerHTML = html;
  }

  // names: every billboard; hanging: the one that hangs from the top instead
  // of standing on a roof (or none).
  function build(home, names, hanging) {
    const roof = names.filter((n) => n !== hanging).slice(0, 3);
    paintCity(home.querySelector(".city"), (SLOTS[roof.length] || []).map((i) => BILLBOARDS[i]));
    addWindows(home.querySelector(".windows"));
    // The glyphs need the VT323 font loaded before they're painted.
    document.fonts.load("16px VT323").catch(() => {}).then(() => {
      home.querySelector(".rain.near").style.backgroundImage = glyphTile(34, 17, "#39ff6a", "#14783f");
      home.querySelector(".rain.far").style.backgroundImage = glyphTile(60, 12, "#0f8f3c", "#04301a");
    });
    home.querySelector(".snow.near").style.backgroundImage = snowTile(60, 4);
    home.querySelector(".snow.far").style.backgroundImage = snowTile(110, 3);
    lightning(home);
    home.querySelector(".stars").style.backgroundImage = starTile();
    document.getElementById("static").style.backgroundImage = staticTile();
    billboards(home.querySelector(".billboards"), roof, names.includes(hanging) ? hanging : null);
  }

  // The scene follows the weather: rain when it rains, stars on a clear night.
  // The weather on Home. Glyph rain as on the Presto (presto's wx.RAIN):
  // heavy in rain, heavier and faster in a thunderstorm (with lightning),
  // light in fog and cloud, none when it's clear or partly cloudy. Snow
  // drifts down when it snows; rain and snow together show both.
  function weather(home, condition, night) {
    const c = (condition || "").toUpperCase();
    const snowing = /SNOW|FLURR|SLEET|BLIZZARD|WINTRY|ICE PELLETS/.test(c);
    const storming = /THUNDER|T-STORM|TSTORM/.test(c);
    const raining = storming || (/RAIN|DRIZZLE|SHOWER/.test(c) && !/SNOW SHOWER/.test(c));
    const clear = /CLEAR|SUNNY|FAIR/.test(c) || c === "";
    const grey = !raining && !snowing && !/PARTLY/.test(c) && /FOG|MIST|HAZE|SMOKE|CLOUD|OVERCAST/.test(c);
    home.classList.toggle("raining", raining);
    home.classList.toggle("storming", storming);
    home.classList.toggle("snowing", snowing);
    home.classList.toggle("misting", grey);
    storm.on = storming;
    home.classList.toggle("clear", clear && !raining);
    home.classList.toggle("night", night);
  }

  // Lightning, while there's a thunderstorm: every 6-16 s on Home, awake and
  // still, the sky flashes and a bolt cracks somewhere over the skyline.
  const storm = { on: false, timer: null };
  function lightning(home) {
    clearTimeout(storm.timer);
    storm.timer = setTimeout(() => {
      const awake = typeof dark === "undefined" || !dark;
      const still = typeof busy === "undefined" || (!busy && current === "home");
      if (storm.on && awake && still) flash(home);
      lightning(home);
    }, 6000 + Math.random() * 10000);
  }

  function flash(home) {
    const bolt = home.querySelector(".bolt");
    bolt.style.left = `${40 + Math.floor(Math.random() * 380)}px`;
    bolt.style.transform = `scale(${Math.random() < 0.5 ? -1 : 1}, 1)`;
    const flicker = [{ opacity: 0 }, { opacity: 1, offset: 0.08 }, { opacity: 0.15, offset: 0.2 },
      { opacity: 0.9, offset: 0.3 }, { opacity: 0, offset: 0.55 }, { opacity: 0.5, offset: 0.62 }, { opacity: 0 }];
    bolt.animate(flicker, { duration: 700, easing: "steps(12)" });
    home.querySelector(".flash").animate(flicker.map((k) => ({ ...k, opacity: k.opacity * 0.55 })),
      { duration: 700, easing: "steps(12)" });
  }

  return { build, weather, flash, COLOURS };
})();

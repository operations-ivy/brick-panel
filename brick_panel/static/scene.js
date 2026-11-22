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
  const BILLBOARDS = [
    { x: 10, top: 568 - 90 },
    { x: 150, top: 610 - 90 },
    { x: 290, top: 582 - 90 },
  ];
  const COLOURS = { alerts: "--red", calendar: "--cyan", shopping: "--green", weather: "--sodium",
    climate: "--rose", lights: "--amber", brick: "--violet" };

  function paintCity(canvas) {
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

  function rainTile(count, width, alpha) {
    return tile(480, 400, (g, r) => {
      g.strokeStyle = `rgba(160,225,255,${alpha})`;
      g.lineWidth = width;
      for (let i = 0; i < count; i++) {
        const x = r() * 480, y = r() * 400, len = 10 + r() * 16;
        g.beginPath();
        g.moveTo(x, y);
        g.lineTo(x - len * 0.1, y + len);
        g.stroke();
        // Wrap the streak across the tile's bottom edge so the loop is seamless.
        if (y + len > 400) {
          g.beginPath();
          g.moveTo(x, y - 400);
          g.lineTo(x - len * 0.1, y - 400 + len);
          g.stroke();
        }
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

  function billboards(el, names) {
    el.innerHTML = names.slice(0, 3).map((name, i) => {
      const b = BILLBOARDS[i];
      return `<button class="billboard" data-open="${name}" style="left:${b.x}px;top:${b.top}px;--c:var(${COLOURS[name] || "--cyan"})">
        <span class="name">${name.toUpperCase()}</span><span class="val">--</span></button>`;
    }).join("");
  }

  function build(home, names) {
    paintCity(home.querySelector(".city"));
    addWindows(home.querySelector(".windows"));
    home.querySelector(".rain.near").style.backgroundImage = rainTile(70, 1.6, 0.45);
    home.querySelector(".rain.far").style.backgroundImage = rainTile(120, 1, 0.3);
    home.querySelector(".stars").style.backgroundImage = starTile();
    document.getElementById("static").style.backgroundImage = staticTile();
    billboards(home.querySelector(".billboards"), names);
  }

  // The scene follows the weather: rain when it rains, stars on a clear night.
  function weather(home, condition, night) {
    const c = (condition || "").toUpperCase();
    const raining = /RAIN|DRIZZLE|SHOWER|THUNDER|STORM/.test(c);
    const clear = /CLEAR|SUNNY|FAIR/.test(c) || c === "";
    home.classList.toggle("raining", raining);
    home.classList.toggle("clear", clear && !raining);
    home.classList.toggle("night", night);
  }

  return { build, weather, COLOURS };
})();

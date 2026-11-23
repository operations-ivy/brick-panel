// Real user monitoring: how the page is doing on the wall (rum.py turns the
// reports into Prometheus metrics). Every 30 s it posts what it gathered:
// each tap's time to the next frame, long tasks, a few seconds of frames
// sampled once a minute while nothing's changing, errors, memory, uptime,
// and the state polls' times. Light by design: a sample, not a recorder.
"use strict";

const RUM = (() => {
  const REPORT_MS = 30000, SAMPLE_EVERY_MS = 60000, SAMPLE_MS = 4000;
  let taps = [], longTasks = [], polls = [], errors = [], idle = null, loaded = true;

  // A tap's time from the finger to the next frame drawn after it.
  function tap(start) {
    requestAnimationFrame(() => setTimeout(() => taps.push(performance.now() - start), 0));
  }

  function poll(ms) {
    if (polls.length < 100) polls.push(ms);
  }

  function error(message, source, line) {
    if (errors.length < 20) errors.push({ message: String(message).slice(0, 300), source: String(source || ""), line: line || 0 });
  }

  // A few seconds of frames on the screen that's up, when no change is
  // running and the screen isn't dark.
  function sample() {
    if (busy || dark) return;
    const screen = current, frames = [];
    let last = 0;
    const t0 = performance.now();
    const tick = (t) => {
      if (busy || current !== screen) return; // a screen change: its own timing covers it
      if (last) frames.push(t - last);
      last = t;
      if (t - t0 < SAMPLE_MS) requestAnimationFrame(tick);
      else idle = { screen, frames };
    };
    requestAnimationFrame(tick);
  }

  function report() {
    const body = { taps, long_tasks: longTasks, polls, errors, idle, loaded, uptime_s: Math.round(performance.now() / 1000) };
    if (performance.memory) body.heap_bytes = performance.memory.usedJSHeapSize;
    taps = []; longTasks = []; polls = []; errors = []; idle = null; loaded = false;
    post("/api/rum", body);
  }

  function start() {
    try {
      new PerformanceObserver((list) => {
        for (const e of list.getEntries()) if (longTasks.length < 200) longTasks.push(e.duration);
      }).observe({ type: "longtask", buffered: true });
    } catch (e) { /* no long task timing: nothing to report */ }
    window.addEventListener("error", (e) => error(e.message, e.filename, e.lineno));
    window.addEventListener("unhandledrejection", (e) => error(`unhandled: ${e.reason}`, "", 0));
    setInterval(report, REPORT_MS);
    setInterval(sample, SAMPLE_EVERY_MS);
  }

  return { start, tap, poll, report };
})();

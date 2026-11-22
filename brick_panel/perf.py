"""How smooth the screen changes are, measured by the page itself.

Every screen change, the page times each frame (requestAnimationFrame) and
posts them here; a frame later than budget x late_factor missed a vsync. The
counts go to Prometheus, so a slow panel shows up on a graph, not by feel.

A bench run is the same thing on demand: deploy/bench asks for one, the page
sees the request in its next state poll, drives the plus round and round, and
posts every frame. The run fails over the p95 or late-ratio limits."""

from __future__ import annotations

import math
import threading
import time
import uuid

from .metrics import Metrics


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(0, math.ceil(pct / 100 * len(ordered)) - 1)
    return ordered[rank]


class Perf:
    def __init__(self, settings: dict, metrics: Metrics, clock=time.time) -> None:
        self.budget = settings["frame_budget_ms"]
        self.late_after = self.budget * settings["late_factor"]
        self.p95_limit = settings["bench_p95_ms"]
        self.late_limit = settings["bench_late_ratio"]
        self.rounds = settings["bench_rounds"]
        self.metrics, self.clock = metrics, clock
        self._lock = threading.Lock()
        self._bench: dict | None = None  # the run asked for or under way
        self.last_bench: dict | None = None

    def late(self, frames: list[float]) -> int:
        return sum(1 for f in frames if f > self.late_after)

    def transition(self, frames: list[float]) -> bool:
        """One screen change's frame times (ms). True when no frame was late."""
        frames = [float(f) for f in frames if 0 < float(f) < 10_000]
        late = self.late(frames)
        m = self.metrics
        m.inc("panel_transitions_total", result="janky" if late else "smooth")
        m.inc("panel_transition_frames_total", len(frames) - late, result="on_time")
        m.inc("panel_transition_frames_total", late, result="late")
        if frames:
            m.set("panel_transition_worst_frame_seconds", max(frames) / 1000)
        return not late

    # Bench runs.

    def request_bench(self) -> str:
        with self._lock:
            self._bench = {"id": uuid.uuid4().hex[:12], "rounds": self.rounds, "asked": self.clock()}
            return self._bench["id"]

    def pending(self) -> dict | None:
        """The run for the page to start, if any."""
        with self._lock:
            return dict(self._bench) if self._bench else None

    def finish_bench(self, run_id: str, frames: list[float]) -> dict | None:
        with self._lock:
            if not self._bench or self._bench["id"] != run_id:
                return None
            self._bench = None
        frames = [float(f) for f in frames if 0 < float(f) < 10_000]
        p95 = percentile(frames, 95)
        late_ratio = self.late(frames) / len(frames) if frames else 1.0
        result = {
            "id": run_id,
            "frames": len(frames),
            "p50_ms": round(percentile(frames, 50), 2),
            "p95_ms": round(p95, 2),
            "worst_ms": round(max(frames, default=0), 2),
            "late_ratio": round(late_ratio, 4),
            "limits": {"p95_ms": self.p95_limit, "late_ratio": self.late_limit},
            "passed": bool(frames) and p95 <= self.p95_limit and late_ratio <= self.late_limit,
            "finished": self.clock(),
        }
        self.last_bench = result
        self.metrics.set("panel_bench_p95_frame_seconds", p95 / 1000)
        self.metrics.set("panel_bench_late_ratio", late_ratio)
        self.metrics.set("panel_bench_timestamp_seconds", result["finished"])
        return result

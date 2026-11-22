from __future__ import annotations

from brick_panel.metrics import Metrics
from brick_panel.perf import percentile
from brick_panel.perf import Perf


def make(settings):
    m = Metrics()
    return Perf(settings["perf"], m, clock=lambda: 1000.0), m


def test_percentile():
    assert percentile([], 95) == 0.0
    assert percentile([1, 2, 3, 4], 50) == 2
    assert percentile(list(range(1, 101)), 95) == 95


def test_a_smooth_transition(settings):
    perf, m = make(settings)
    assert perf.transition([16.6] * 18) is True
    assert m.get("panel_transitions_total", result="smooth") == 1
    assert m.get("panel_transition_frames_total", result="on_time") == 18
    assert m.get("panel_transition_frames_total", result="late") == 0


def test_one_missed_vsync_is_janky(settings):
    perf, m = make(settings)
    assert perf.transition([16.6] * 17 + [33.4]) is False
    assert m.get("panel_transitions_total", result="janky") == 1
    assert m.get("panel_transition_frames_total", result="late") == 1
    assert m.get("panel_transition_worst_frame_seconds") == 33.4 / 1000


def test_nonsense_frames_are_dropped(settings):
    perf, m = make(settings)
    assert perf.transition([16.6, -5, 0, 1e9, "16.7"]) is True
    assert m.get("panel_transition_frames_total", result="on_time") == 2


def test_bench_run_passes_and_fails(settings):
    perf, m = make(settings)
    run = perf.request_bench()
    assert perf.pending()["id"] == run
    good = perf.finish_bench(run, [16.6] * 400)
    assert good["passed"] and good["late_ratio"] == 0 and perf.pending() is None
    assert m.get("panel_bench_p95_frame_seconds") == 0.0166

    run = perf.request_bench()
    bad = perf.finish_bench(run, [16.6] * 90 + [40] * 10)
    assert not bad["passed"]
    assert bad["late_ratio"] == 0.1


def test_bench_needs_the_run_asked_for(settings):
    perf, _ = make(settings)
    assert perf.finish_bench("nope", [16.6]) is None
    run = perf.request_bench()
    assert perf.finish_bench("other", [16.6]) is None
    assert perf.finish_bench(run, []) == perf.last_bench
    assert perf.last_bench["passed"] is False  # no frames is no proof

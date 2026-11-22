from __future__ import annotations

from brick_panel.metrics import Metrics


def test_known_counters_start_at_zero():
    text = Metrics().render()
    assert 'panel_transitions_total{result="janky"} 0' in text
    assert 'panel_transition_frames_total{result="late"} 0' in text


def test_render_groups_by_name_with_help():
    m = Metrics()
    m.inc("panel_transitions_total", result="smooth")
    m.inc("panel_transitions_total", result="smooth")
    m.set("panel_screen", 1, screen="home")
    text = m.render()
    assert text.count("# TYPE panel_transitions_total counter") == 1
    assert 'panel_transitions_total{result="smooth"} 2' in text
    assert 'panel_screen{screen="home"} 1' in text


def test_label_values_are_escaped():
    m = Metrics()
    m.set("panel_info", 1, version='a"b\\c\nd')
    assert 'panel_info{version="a\\"b\\\\c\\nd"} 1' in m.render()

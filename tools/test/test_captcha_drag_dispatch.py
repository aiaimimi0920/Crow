"""Input-event correctness only; no third-party verification requests."""

import random

import pytest

from src import captcha_slider


class Pointer(captcha_slider.CaptchaSliderMixin):
    def __init__(self):
        self.events = []
        self.waits = []
        self.released = False

    def _send_cdp(self, method, params):
        assert method == "Input.dispatchMouseEvent"
        self.events.append(dict(params))
        return {}

    def _wait_interruptibly(self, seconds):
        self.waits.append(seconds)

    def _stop_if_cancelled(self):
        return False

    def _release_cdp_mouse(self):
        self.released = True


def seeded_random(monkeypatch, seed):
    generator = random.Random(seed)
    for name in ("uniform", "gauss", "random", "randint", "choice"):
        monkeypatch.setattr(captcha_slider.random, name, getattr(generator, name))


def test_dispatch_uses_browser_default_timestamp_and_preserves_buttons():
    pointer = Pointer()
    assert pointer._dispatch_mouse("mousePressed", 100, 50, buttons=1)
    assert "timestamp" not in pointer.events[0]
    assert pointer.events[0]["button"] == "left"
    assert pointer.events[0]["buttons"] == 1
    assert pointer._cdp_mouse_down
    assert pointer._dispatch_mouse("mouseReleased", 120, 50)
    assert not pointer._cdp_mouse_down


@pytest.mark.parametrize("seed", range(20))
def test_short_drag_stays_within_endpoint_and_releases(monkeypatch, seed):
    seeded_random(monkeypatch, seed)
    pointer = Pointer()
    assert pointer._do_drag(100, 50, 260) == 360
    moves = [e for e in pointer.events if e["type"] == "mouseMoved" and e["buttons"]]
    positions = [e["x"] for e in moves]
    assert positions == sorted(positions)
    assert all(100 <= value <= 360 for value in positions)
    assert pointer.events[-1]["type"] == "mouseReleased"
    assert pointer.events[-1]["x"] == 360
    assert pointer.events[-1]["buttons"] == 0
    assert not pointer._cdp_mouse_down
    assert 0 < sum(pointer.waits) < 1.5


def test_overshooting_injected_path_is_clamped(monkeypatch):
    seeded_random(monkeypatch, 7)
    pointer = Pointer()
    monkeypatch.setattr(pointer, "_generate_bezier_path", lambda *_: [(500, 50, 0.5)])
    assert pointer._do_drag(100, 50, 260) == 360
    assert all(e["x"] <= 360 for e in pointer.events)


def test_unacknowledged_input_preserves_failure_and_release(monkeypatch):
    pointer = Pointer()
    monkeypatch.setattr(pointer, "_send_cdp", lambda *_: None)
    assert pointer._do_drag(100, 50, 260) is None
    assert pointer.released
    assert pointer.last_failure_reason == "cdp_unavailable"

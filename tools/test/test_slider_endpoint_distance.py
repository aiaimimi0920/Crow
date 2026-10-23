"""An exhausted slider must not turn a border offset into a full-track retry."""

import pytest

from src.captcha_slider import CaptchaSliderMixin


@pytest.mark.parametrize("overshoot", [0, 0.5, 1.5, 2])
@pytest.mark.parametrize("with_offsets", [False, True])
def test_endpoint_border_overshoot_uses_minimum_motion(overshoot, with_offsets):
    track = {"left": 565.5, "width": 300}
    handle = {"x": 565.5 + 300 - 42 + overshoot, "width": 42}
    if with_offsets:
        track.update(offsetWidth=300, handleOffsetWidth=42, handleOffsetLeft=258 + overshoot)
    assert CaptchaSliderMixin()._remaining_drag_distance(handle, track, 300) == 1


@pytest.mark.parametrize(("left", "expected"), [(2, 256), (100, 158), (250, 8)])
def test_nonterminal_remaining_distance_is_unchanged(left, expected):
    track = {
        "left": 565.5, "width": 300, "offsetWidth": 300,
        "handleOffsetWidth": 42, "handleOffsetLeft": left,
    }
    handle = {"x": 565.5 + left, "width": 42}
    assert CaptchaSliderMixin()._remaining_drag_distance(handle, track, 300) == expected


def test_unknown_geometry_retains_existing_bounded_fallback():
    assert CaptchaSliderMixin()._remaining_drag_distance({"x": 2, "width": 42}, None, 300) == 260

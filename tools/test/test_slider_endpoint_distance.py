"""An exhausted slider must not turn a border offset into a full-track retry."""

import pytest

from src.captcha_slider import CaptchaSliderMixin


@pytest.mark.parametrize("overshoot", [0, 0.5, 1.5, 2])
@pytest.mark.parametrize("with_offsets", [False, True])
def test_endpoint_border_overshoot_has_no_remaining_motion(overshoot, with_offsets):
    track = {"left": 565.5, "width": 300}
    handle = {"x": 565.5 + 300 - 42 + overshoot, "width": 42}
    if with_offsets:
        track.update(
            offsetWidth=300, handleOffsetWidth=42, handleOffsetLeft=258 + overshoot
        )
    assert CaptchaSliderMixin()._remaining_drag_distance(handle, track, 300) == 0


@pytest.mark.parametrize(("left", "expected"), [(2, 256), (100, 158), (250, 8)])
def test_nonterminal_remaining_distance_is_unchanged(left, expected):
    track = {
        "left": 565.5,
        "width": 300,
        "offsetWidth": 300,
        "handleOffsetWidth": 42,
        "handleOffsetLeft": left,
    }
    handle = {"x": 565.5 + left, "width": 42}
    assert CaptchaSliderMixin()._remaining_drag_distance(handle, track, 300) == expected


def test_unknown_geometry_retains_existing_bounded_fallback():
    assert (
        CaptchaSliderMixin()._remaining_drag_distance({"x": 2, "width": 42}, None, 300)
        == 260
    )


@pytest.mark.parametrize("track", [None, {}])
def test_unknown_geometry_does_not_turn_fallback_arithmetic_into_endpoint_proof(track):
    assert (
        CaptchaSliderMixin()._remaining_drag_distance(
            {"x": 2, "width": 302}, track, 300
        )
        == 1
    )


@pytest.mark.parametrize("scale", [0.5, 1, 2])
@pytest.mark.parametrize("left", [2, 100, 250])
def test_layout_offsets_are_converted_to_viewport_css_distance(scale, left):
    track = {
        "left": 100,
        "width": 300 * scale,
        "offsetWidth": 300,
        "handleOffsetWidth": 42,
        "handleOffsetLeft": left,
    }
    handle = {"x": 100 + left * scale, "width": 42 * scale}
    expected = (300 - 42 - left) * scale
    assert CaptchaSliderMixin()._remaining_drag_distance(
        handle, track, track["width"]
    ) == pytest.approx(expected)


@pytest.mark.parametrize("scale", [0.5, 2])
@pytest.mark.parametrize("overshoot", [0, 0.5, 1.5, 2])
def test_scaled_endpoint_overshoot_still_has_no_remaining_motion(scale, overshoot):
    track = {
        "left": 100,
        "width": 300 * scale,
        "offsetWidth": 300,
        "handleOffsetWidth": 42,
        "handleOffsetLeft": 258 + overshoot / scale,
    }
    handle = {"x": 100 + 258 * scale + overshoot, "width": 42 * scale}
    assert (
        CaptchaSliderMixin()._remaining_drag_distance(handle, track, track["width"])
        == 0
    )


@pytest.mark.parametrize(
    "missing", ["offsetWidth", "handleOffsetWidth", "handleOffsetLeft"]
)
def test_incomplete_layout_offsets_do_not_override_viewport_geometry(missing):
    track = {
        "left": 100,
        "width": 600,
        "offsetWidth": 300,
        "handleOffsetWidth": 42,
        "handleOffsetLeft": 100,
    }
    del track[missing]
    handle = {"x": 300, "width": 84}
    assert CaptchaSliderMixin()._remaining_drag_distance(handle, track, 600) == 316

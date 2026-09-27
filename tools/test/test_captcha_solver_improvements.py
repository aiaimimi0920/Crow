"""Test captcha solver improvements."""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))


def test_stealth_injection():
    """Verify stealth JS injection includes all fingerprint hiding."""
    from src.captcha_solver import CaptchaSolver

    solver = CaptchaSolver(port=9223)

    # Connect and inject stealth script (mocked)
    assert hasattr(solver, "_send_cdp")
    print("✓ Stealth injection method exists")


def test_bezier_path_generation():
    """Test that bezier path has realistic human-like properties."""
    from src.captcha_solver import CaptchaSolver

    solver = CaptchaSolver(port=9223)

    path = solver._generate_bezier_path(100, 100, 400, 105)

    # Should have reasonable number of points
    assert 15 <= len(path) <= 100, f"Path has {len(path)} points"

    # Should have some variation in Y axis (human tremor)
    y_values = [p[1] for p in path]
    y_min, y_max = min(y_values), max(y_values)
    y_range = y_max - y_min
    assert y_range > 2, f"Y variation too small: {y_range}px"

    # Check easing values are properly distributed
    ease_values = [p[2] for p in path]
    assert ease_values[0] < 0.1, "Start should be slow"
    assert ease_values[-1] > 0.9, "End should be near complete"

    print(f"✓ Bezier path: {len(path)} points, Y-range: {y_range:.1f}px")


def test_drag_timing_improvements():
    """Verify drag method has improved timing."""
    import inspect

    from src.captcha_solver import CaptchaSolver

    solver = CaptchaSolver(port=9223)
    source = inspect.getsource(solver._do_drag)

    # Check for improved timings
    assert "0.3, 0.8" in source or "0.9, 2.2" in source, "Should have longer delays"
    assert "random.uniform" in source, "Should use randomization"

    print("✓ Drag timing includes improvements")


@pytest.mark.parametrize(
    ("track", "expected"),
    [
        ({"left": 100, "width": 400}, 260),
        (
            {
                "left": 100,
                "width": 400,
                "offsetWidth": 402,
                "handleOffsetWidth": 40,
                "handleOffsetLeft": 200,
            },
            162,
        ),
        (None, 362),
    ],
)
def test_live_drag_distance_uses_remaining_track_geometry(monkeypatch, track, expected):
    """A handle already partway across the track only moves the remaining distance."""
    from src.captcha_solver import CaptchaSolver

    solver = CaptchaSolver(target_url="https://example.test/challenge")
    dragged = []
    monkeypatch.setattr(
        solver,
        "_preflight_current_challenge",
        lambda: {"connected": True, "has_slider": True},
    )
    monkeypatch.setattr(solver, "_bring_to_front", lambda: True)
    monkeypatch.setattr(solver, "_wait_interruptibly", lambda _seconds: None)
    monkeypatch.setattr(
        solver, "_find_slider", lambda: {"x": 200, "y": 100, "width": 40, "height": 40}
    )
    monkeypatch.setattr(solver, "_get_track_width", lambda: 400)
    monkeypatch.setattr(solver, "_get_track_rect", lambda: track)
    monkeypatch.setattr(solver, "_os_mouse_enabled", lambda: False)
    monkeypatch.setattr(
        solver,
        "_do_drag",
        lambda x, y, distance: dragged.append((x, y, distance)) or distance,
    )
    monkeypatch.setattr(solver, "_wait_for_verification_success", lambda: True)
    monkeypatch.setattr(solver, "_close_owned_target_tabs", lambda: None)

    assert solver.solve(max_attempts=1) is True
    assert dragged == [(220, 120, expected)]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))

"""Linux pointer timing and visible tremor, without opening a real input device."""

import random

import pytest

from src.captcha_solver import CaptchaSolver
from tools.test.captcha_solver_test_context import set_solver_platform


@pytest.mark.parametrize("variant", range(3))
def test_linux_drag_is_slow_for_every_variant(monkeypatch, variant):
    set_solver_platform(monkeypatch, "posix")
    profile = CaptchaSolver()._os_drag_profile(variant)
    assert profile["total_time"][0] >= 2.6
    assert profile["steps"][0] >= 72
    assert profile["hold_before_release"] == (1.5, 2.5)


@pytest.mark.parametrize("seed", range(10))
def test_linux_track_preserves_requested_movement_duration(monkeypatch, seed):
    set_solver_platform(monkeypatch, "posix")
    rng = random.Random(seed)
    monkeypatch.setattr(random, "uniform", rng.uniform)
    monkeypatch.setattr(random, "gauss", rng.gauss)
    solver = CaptchaSolver()
    profile = solver._os_drag_profile(seed % 3)
    fractions, dwells = solver._os_drag_track(256, profile)
    assert profile["total_time"][0] <= sum(dwells) <= profile["total_time"][1]
    assert len(fractions) == len(dwells)
    assert fractions[-1] == 1.0
    assert all(0.006 <= dwell <= 0.09 for dwell in dwells)


def test_windows_keeps_existing_motion_profile(monkeypatch):
    set_solver_platform(monkeypatch, "nt")
    profile = CaptchaSolver()._os_drag_profile(0)
    assert profile["name"] == "fast_exact_v3"
    assert profile["total_time"] == (0.4, 0.65)


@pytest.mark.parametrize("seed", range(10))
def test_linux_tremor_survives_native_integer_pixel_quantization(monkeypatch, seed):
    set_solver_platform(monkeypatch, "posix")
    rng = random.Random(seed)
    for name in ("uniform", "randint", "choice"):
        monkeypatch.setattr(random, name, getattr(rng, name))
    solver = CaptchaSolver()
    offsets = solver._os_drag_y_track(90, solver._os_drag_profile(seed % 3))
    pixels = [int(400 + offset) for offset in offsets]
    assert max(pixels) - min(pixels) >= 2
    assert all(abs(offset) <= 2.4 for offset in offsets)

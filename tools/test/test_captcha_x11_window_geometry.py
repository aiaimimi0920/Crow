"""Use root-relative window coordinates, not reparented frame offsets."""

from types import SimpleNamespace

import pytest

from src import captcha_os_windows, captcha_solver
from tools.test.captcha_solver_test_context import set_solver_platform

ROOT_GEOMETRY = """
xwininfo: Window id: 0x200003 "Browser"
  Absolute upper-left X:  0
  Absolute upper-left Y:  -23
  Relative upper-left X:  0
  Relative upper-left Y:  19
  Width: 1439
  Height: 899
"""
REPARENTED_GEOMETRY = "WINDOW=2097155\nX=0\nY=-4\nWIDTH=1439\nHEIGHT=899\n"


def make_solver(monkeypatch):
    set_solver_platform(monkeypatch, "posix")
    solver = captcha_solver.CaptchaSolver(port=9223)
    solver._linux_window_id = "2097155"
    return solver


def install_geometry_reader(monkeypatch, output=ROOT_GEOMETRY):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        stdout = REPARENTED_GEOMETRY if command[0] == "xdotool" else output
        return SimpleNamespace(returncode=0, stdout=stdout)

    monkeypatch.setattr(captcha_os_windows.subprocess, "run", run)
    return calls


def test_x11_geometry_reads_absolute_origin_and_keeps_display(monkeypatch):
    solver = make_solver(monkeypatch)
    monkeypatch.setenv("DISPLAY", ":123")
    monkeypatch.setenv("LC_ALL", "zh_CN.UTF-8")
    calls = install_geometry_reader(monkeypatch)

    assert solver._linux_window_geometry() == {
        "x": 0.0,
        "y": -23.0,
        "width": 1439.0,
        "height": 899.0,
    }
    command, options = calls[0]
    assert command == ["xwininfo", "-id", "2097155", "-stats"]
    assert options["env"]["LC_ALL"] == "C"
    assert options["env"]["DISPLAY"] == ":123"
    assert options["timeout"] == 3


def test_live_reparented_window_maps_inside_slider_not_below_it(monkeypatch):
    solver = make_solver(monkeypatch)
    install_geometry_reader(monkeypatch)
    solver._target_activation_verified = True
    solver._linux_window_frame_extents = lambda: {
        "left": 1.0,
        "right": 1.0,
        "top": 20.0,
        "bottom": 4.0,
    }
    solver._window_metrics = lambda: {
        "innerWidth": 1439,
        "innerHeight": 812,
        "outerWidth": 1439,
        "outerHeight": 899,
        "dpr": 1,
    }
    solver._browser_window_bounds = lambda: {
        "left": -1,
        "top": -24,
        "width": 1439,
        "height": 899,
    }

    mapped = solver._css_to_x11_window_screen(592.5, 506, 256)

    assert mapped is not None
    assert 554 <= mapped["y"] < 584
    assert mapped["y"] == 566
    assert mapped["x"] == 592.5
    assert mapped["distance"] == 256
    assert mapped["frame_bottom"] == 4


@pytest.mark.parametrize(
    "output",
    [
        ROOT_GEOMETRY.replace("  Absolute upper-left Y:  -23\n", ""),
        ROOT_GEOMETRY.replace("  Absolute upper-left X:  0\n", ""),
        ROOT_GEOMETRY.replace("  Width: 1439\n", ""),
        ROOT_GEOMETRY.replace("  Height: 899\n", ""),
        ROOT_GEOMETRY.replace("Width: 1439", "Width: 199"),
        ROOT_GEOMETRY.replace("Height: 899", "Height: -1"),
        ROOT_GEOMETRY.replace("Y:  -23", "Y:  nan"),
        ROOT_GEOMETRY.replace("Y:  -23", "Y:  -23 trailing"),
        ROOT_GEOMETRY + "  Absolute upper-left Y:  19\n",
    ],
)
def test_x11_geometry_rejects_incomplete_or_ambiguous_output(monkeypatch, output):
    solver = make_solver(monkeypatch)
    install_geometry_reader(monkeypatch, output)
    assert solver._linux_window_geometry() is None


@pytest.mark.parametrize("error", [FileNotFoundError(), OSError("X unavailable")])
def test_x11_geometry_returns_unavailable_when_query_cannot_start(monkeypatch, error):
    solver = make_solver(monkeypatch)

    def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(captcha_os_windows.subprocess, "run", fail)
    assert solver._linux_window_geometry() is None


def test_x11_geometry_returns_unavailable_after_query_failure(monkeypatch):
    solver = make_solver(monkeypatch)
    monkeypatch.setattr(
        captcha_os_windows.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout=ROOT_GEOMETRY),
    )
    assert solver._linux_window_geometry() is None


@pytest.mark.parametrize("platform,window_id", [("nt", "2097155"), ("posix", "")])
def test_x11_geometry_skips_unsupported_platform_or_missing_id(
    monkeypatch, platform, window_id
):
    solver = make_solver(monkeypatch)
    set_solver_platform(monkeypatch, platform)
    solver._linux_window_id = window_id
    calls = install_geometry_reader(monkeypatch)
    assert solver._linux_window_geometry() is None
    assert calls == []

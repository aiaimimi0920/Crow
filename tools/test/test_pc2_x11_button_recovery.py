from __future__ import annotations

import os
import sys
from copy import deepcopy
from types import SimpleNamespace

import pytest

from src import captcha_os_input, captcha_x11_pointer
from src.captcha_solver import CaptchaSolver


def pointer_rows(owner="xwayland-relative-pointer:16", *, pressed=True):
    return [
        {
            "id": 2,
            "name": "Virtual core pointer",
            "use": 1,
            "attachment": 3,
            "enabled": True,
            "left_pressed": pressed,
        },
        {
            "id": 4,
            "name": "Virtual core XTEST pointer",
            "use": 3,
            "attachment": 2,
            "enabled": True,
            "left_pressed": False,
        },
        {
            "id": 7,
            "name": owner,
            "use": 3,
            "attachment": 2,
            "enabled": True,
            "left_pressed": pressed,
        },
    ]


@pytest.fixture
def pointer(monkeypatch):
    class FakePointer:
        rows = pointer_rows()
        releases = []
        closed = False
        confirm = True

        def states(self):
            return deepcopy(self.rows)

        def release(self, device_id):
            self.releases.append(device_id)
            if self.confirm:
                self.rows = pointer_rows(pressed=False)

        def close(self):
            self.closed = True

    instance = FakePointer()
    monkeypatch.setattr(captcha_x11_pointer, "_X11Pointer", lambda: instance)
    monkeypatch.setattr(captcha_x11_pointer.time, "sleep", lambda _seconds: None)
    return instance


def test_releases_only_stale_relative_pointer_and_confirms_core_state(pointer):
    result = captcha_x11_pointer.recover_xwayland_left_button()

    assert result == {"verified": True, "released": [7]}
    assert pointer.releases == [7]
    assert pointer.closed


@pytest.mark.parametrize(
    "owner", ["Virtual core XTEST pointer", "USB Mouse", "xwayland-pointer:16"]
)
def test_does_not_release_another_input_owner(pointer, owner):
    pointer.rows = pointer_rows(owner)

    result = captcha_x11_pointer.recover_xwayland_left_button()

    assert result["verified"] is False
    assert pointer.releases == []
    assert pointer.closed


def test_released_pointer_needs_no_injection(pointer):
    pointer.rows = pointer_rows(pressed=False)

    assert captcha_x11_pointer.recover_xwayland_left_button()["verified"] is True
    assert pointer.releases == []


def test_release_request_without_confirmation_is_not_success(pointer):
    pointer.confirm = False

    result = captcha_x11_pointer.recover_xwayland_left_button()

    assert result["verified"] is False
    assert result["reason"] == "button_release_unconfirmed"
    assert pointer.closed


def test_owner_change_between_samples_prevents_injection(pointer):
    snapshots = iter([pointer_rows(), pointer_rows("USB Mouse")])
    pointer.states = lambda: next(snapshots)

    assert captcha_x11_pointer.recover_xwayland_left_button()["verified"] is False
    assert pointer.releases == []


def test_server_release_error_closes_the_display(pointer):
    def failed_release(_device_id):
        raise RuntimeError("device disappeared")

    pointer.release = failed_release

    assert captcha_x11_pointer.recover_xwayland_left_button()["verified"] is False
    assert pointer.closed


def test_drag_stops_before_motion_when_button_release_is_not_verified(monkeypatch):
    monkeypatch.setattr(
        captcha_os_input, "os", SimpleNamespace(name="posix", getenv=os.getenv)
    )
    monkeypatch.setattr(
        captcha_os_input, "recover_xwayland_left_button", lambda: {"verified": False}
    )
    monkeypatch.setitem(
        sys.modules, "pyautogui", SimpleNamespace(FAILSAFE=True, PAUSE=0)
    )
    monkeypatch.setenv("FAPAI_SOLVER_OS_INPUT_BACKEND", "pyautogui")
    solver = CaptchaSolver(port=9223)
    monkeypatch.setattr(solver, "_wait_interruptibly", lambda _seconds: None)
    solver._focus_os_window = lambda: True
    solver._map_css_to_screen = lambda *_args, **_kwargs: {
        "x": 593,
        "y": 604,
        "distance": 256,
        "located": True,
        "source": "x11_window_geometry",
    }
    solver._move_os_cursor_timed = lambda *_args: pytest.fail(
        "Motion while left button is held"
    )

    assert solver._do_drag_os(577, 486, 256, slider_info={}) is None
    assert solver.last_failure_reason == "os_button_state_unverified"

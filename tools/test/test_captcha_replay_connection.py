"""A recovered owned challenge must not lose its navigation authority on replay."""

from unittest.mock import Mock

import pytest

from src.captcha_challenge_binding import challenge_binding_is_current
from tools.test.navigation_flow_fixtures import CHALLENGE, NEXT, prepared, scripted


def replay_solver(path, *, change_document=False):
    solver, sock = prepared(scripted(), loader=NEXT)
    original = solver._send_cdp
    geometry_reads = []
    ready = {
        "href": CHALLENGE,
        "readyState": "complete",
        "hasSlider": True,
        "hardBlock": True,
    }
    waiting = {**ready, "hasSlider": False}

    def send(method, params=None):
        assert not method.startswith("Input.")
        if method == "Runtime.evaluate":
            geometry_reads.append(solver.ws)
            if path == "before_drag" and len(geometry_reads) == 1:
                return {"result": {"value": {"found": False}}}
            return {
                "result": {
                    "value": {
                        **ready,
                        "found": True,
                        "binding_key": "fixture",
                        "selector": "#handle",
                        "x": 100,
                        "y": 100,
                        "width": 40,
                        "height": 30,
                        "track_rect": None,
                    }
                }
            }
        return original(method, params)

    solver._send_cdp = send
    solver._preflight_current_challenge = Mock(
        return_value={"connected": True, "has_slider": path != "before_drag"}
    )
    solver._page_challenge_summary = Mock(
        side_effect=[waiting, ready]
        if path == "before_drag"
        else [
            {
                **ready,
                "explicitFailure": path == "after_retry",
                "retryableFailure": path == "after_retry",
            }
        ]
    )
    solver._wait_interruptibly = Mock()
    solver._bring_to_front = Mock()
    solver._close_owned_target_tabs = Mock()
    # The real reconnect would discard the old trace or use a different socket.
    # Neither is necessary to replay a still-current, already connected document.
    solver.connect_tab = Mock(return_value=False)
    solver._recover_authenticated_list_page = Mock(return_value=False)
    solver._os_mouse_enabled = Mock(return_value=True)
    solver._wait_for_verification_success = Mock(return_value=False)
    solver._do_drag = Mock()
    drags = []

    def drag(*_args, slider_info, **_kwargs):
        assert solver.ws is sock and sock.connected
        assert challenge_binding_is_current(solver, slider_info["_challenge_binding"])
        drags.append(slider_info)
        if path != "before_drag" and len(drags) == 1:
            if change_document:
                sock.loader = "REPLACED_DOCUMENT"
            return 1
        return None  # No fake success: this regression only proves input admission.

    solver._do_drag_os = Mock(side_effect=drag)
    solver._reset_failed_nc_challenge = Mock(return_value=path == "after_retry")
    return solver, sock, geometry_reads, drags


@pytest.mark.parametrize("path", ["before_drag", "after_drag", "after_retry"])
def test_replay_keeps_owned_navigation_socket_and_revalidates_geometry(path):
    solver, sock, reads, drags = replay_solver(path)
    assert (
        solver.solve(max_attempts=1, nc_retry_replay_limit=1, slider_find_max_retries=1)
        is False
    )
    assert len(drags) == (1 if path == "before_drag" else 2)
    assert len(reads) == 2 and all(connection is sock for connection in reads)
    if len(drags) == 2:
        assert drags[0] is not drags[1]
    solver.connect_tab.assert_not_called()
    solver._do_drag.assert_not_called()
    solver._recover_authenticated_list_page.assert_not_called()
    assert sum(m["method"] == "Page.navigate" for m in sock.messages) == 1
    assert solver.last_failure_reason == "execution_unavailable"
    assert not solver.lock.locked() and solver._solve_budget is None


def test_retaining_connection_does_not_retain_authority_for_replaced_document():
    solver, _sock, _reads, drags = replay_solver("after_drag", change_document=True)
    # After the first failed drag, the replacement loader has no trusted commit.
    solver._page_challenge_summary = Mock(
        return_value={
            "href": CHALLENGE,
            "readyState": "complete",
            "hasSlider": True,
        }
    )
    assert solver.solve(max_attempts=1, nc_retry_replay_limit=1) is False
    assert len(drags) == 1
    solver.connect_tab.assert_not_called()
    solver._do_drag.assert_not_called()
    assert solver.last_failure_reason == "slider_not_found"

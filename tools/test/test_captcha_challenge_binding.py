"""Owned queryless navigation may authorize native input, never authentication."""

from unittest.mock import Mock

import pytest

from src.captcha_challenge_binding import (
    challenge_binding_is_current,
    challenge_input_binding,
    input_target_matches,
)
from src.captcha_navigation_flow import observe_navigation_event
from src.captcha_verification import finalize_page_summary, ready_target_matches
from tools.test.navigation_flow_fixtures import (
    CHALLENGE,
    FIRST,
    FRAME,
    NEXT,
    TARGET,
    direct,
    event,
    prepared,
    request,
    scripted,
)


def summary(**updates):
    return {"href": CHALLENGE, "readyState": "complete", "hasSlider": True, **updates}


@pytest.mark.parametrize(
    "flow,loader",
    [(direct, FIRST), (scripted, NEXT), (lambda: scripted("metaTagRefresh"), NEXT)],
)
def test_trusted_owned_challenge_input_does_not_change_success_authority(flow, loader):
    solver, sock = prepared(flow(), loader=loader)
    evidence = summary()
    binding = challenge_input_binding(solver, evidence)
    assert binding is not None
    assert challenge_binding_is_current(solver, binding)
    assert input_target_matches(solver, evidence)
    assert not ready_target_matches(evidence, TARGET)
    assert finalize_page_summary(evidence, TARGET)["authenticatedPage"] is False
    assert sum(m["method"] == "Page.navigate" for m in sock.messages) == 1
    assert "PRIVATE" not in repr(binding)


@pytest.mark.parametrize(
    "change",
    [
        "initial",
        "pending",
        "loader",
        "away_return",
        "unsupported",
        "missing_request",
        "limited",
        "unavailable",
        "socket",
        "ownership",
        "receipt",
        "url",
        "loading",
        "login",
        "probe",
        "auth",
    ],
)
def test_incomplete_or_untrusted_chains_cannot_authorize_input(change):
    events = scripted()
    if change == "initial":
        events[0] = request(TARGET + "&page=3")
    elif change == "pending":
        events.append(
            event(
                "Page.frameRequestedNavigation",
                frameId=FRAME,
                url=CHALLENGE,
                reason="scriptInitiated",
            )
        )
    elif change == "away_return":
        events[2] = event(
            "Page.frameRequestedNavigation",
            frameId=FRAME,
            url="https://evil.invalid/",
            reason="scriptInitiated",
        )
    elif change == "unsupported":
        events = scripted("anchorClick")
    elif change == "missing_request":
        events.pop(3)
    solver, sock = prepared(events, loader="changed" if change == "loader" else NEXT)
    evidence = summary()
    if change in {"limited", "unavailable"}:
        solver._navigation_trace.state = change
    elif change == "socket":
        solver.ws = Mock(connected=True)
    elif change == "ownership":
        solver._opened_target_ids.clear()
    elif change == "receipt":
        solver._navigation_receipt = None
    elif change == "url":
        evidence["href"] += "&other=value"
    elif change == "loading":
        evidence["readyState"] = "loading"
    elif change == "login":
        evidence["loginRequired"] = True
    elif change == "probe":
        evidence["probeFailed"] = True
    elif change == "auth":
        evidence["authenticatedPage"] = True
    assert challenge_input_binding(solver, evidence) is None
    assert not any(m["method"].startswith("Input.") for m in sock.messages)


@pytest.mark.parametrize(
    "change", ["requested", "loader", "socket", "disconnect", "target"]
)
def test_qualification_is_not_reusable_after_a_document_or_socket_change(change):
    solver, sock = prepared(direct())
    binding = challenge_input_binding(solver, summary())
    if change == "requested":
        observe_navigation_event(
            solver,
            sock,
            event(
                "Page.frameRequestedNavigation",
                frameId=FRAME,
                url=CHALLENGE,
                reason="scriptInitiated",
            ),
        )
    elif change == "loader":
        sock.loader = NEXT
    elif change == "socket":
        solver.ws = Mock(connected=True)
    elif change == "disconnect":
        sock.connected = False
    else:
        solver.target_id = "other"
    assert not challenge_binding_is_current(solver, binding)


def test_geometry_bracket_rejects_navigation_even_to_the_same_url():
    solver, _ = prepared(scripted(), loader=NEXT)
    assert (
        challenge_input_binding(
            solver, summary(), before={"id": FRAME, "loaderId": FIRST, "url": CHALLENGE}
        )
        is None
    )


def test_wrong_scope_or_unowned_target_never_borrows_seed_authority():
    for options in (
        {"owned": False},
        {"target": "https://sf-item.taobao.com/sf_item/123.htm"},
    ):
        solver, _ = prepared(direct(), **options)
        assert challenge_input_binding(solver, summary()) is None


def test_frame_probe_failure_is_not_an_input_grant():
    solver, _ = prepared(direct())
    solver._send_cdp = Mock(return_value=None)
    assert challenge_input_binding(solver, summary()) is None


@pytest.mark.parametrize("navigate", [False, True])
def test_real_geometry_reader_binds_the_atomic_snapshot_or_discards_it(navigate):
    solver, sock = prepared(direct())
    original = solver._send_cdp

    def send(method, params=None):
        if method == "Runtime.evaluate":
            if navigate:
                sock.loader = NEXT
            return {
                "result": {
                    "value": {**summary(), "found": True, "binding_key": "fixture"}
                }
            }
        return original(method, params)

    solver._send_cdp = send
    geometry = solver._read_slider_geometry(binding_key="fixture")
    if navigate:
        assert geometry is None
    else:
        assert challenge_binding_is_current(solver, geometry["_challenge_binding"])


def test_native_pointer_rechecks_navigation_before_permitting_press(monkeypatch):
    from tools.test.test_captcha_os_target import make_probe, pointer_event, snapshot

    solver, sock = prepared(direct())
    binding = challenge_input_binding(solver, summary())
    probe, pointer_solver, _, _ = make_probe(
        monkeypatch, [snapshot(), snapshot(pointer_event(220, 165))]
    )
    # The independent native-pointer fixture remains real; only navigation calls
    # are delegated to the actual event/ACK solver fixture.
    monkeypatch.setattr(
        "src.captcha_os_target.challenge_binding_is_current",
        lambda _s, b: challenge_binding_is_current(solver, b),
    )
    probe.info = {**probe.info, "_challenge_binding": binding}
    assert probe.open()
    pointer_solver._get_os_cursor_position = lambda _: (236, 197)
    observe_navigation_event(
        solver,
        sock,
        event(
            "Page.frameRequestedNavigation",
            frameId=FRAME,
            url=CHALLENGE,
            reason="scriptInitiated",
        ),
    )
    assert probe.verify(None, {"x": 236, "y": 197}) is None
    assert pointer_solver.last_failure_reason == "screen_mapping_target_unavailable"


@pytest.mark.parametrize("native_enabled", [True, False])
def test_production_solve_never_falls_back_to_cdp_for_queryless_geometry(
    native_enabled,
):
    solver, _sock = prepared(direct())
    original = solver._send_cdp

    def send(method, params=None):
        assert not method.startswith("Input.")
        if method == "Runtime.evaluate":
            return {
                "result": {
                    "value": {
                        **summary(),
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
        return_value={"connected": True, "has_slider": True}
    )
    solver._wait_interruptibly = Mock()
    solver._bring_to_front = Mock()
    solver._close_owned_target_tabs = Mock()
    solver._os_mouse_enabled = Mock(return_value=native_enabled)
    solver._do_drag_os = Mock(return_value=None)
    solver._do_drag = Mock()
    assert solver.solve(max_attempts=1, slider_find_max_retries=1) is False
    solver._do_drag.assert_not_called()
    assert solver._do_drag_os.call_count == int(native_enabled)
    assert solver.last_failure_reason == "execution_unavailable"

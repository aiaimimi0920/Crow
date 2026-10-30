"""Native flow telemetry narrows queryless failures, never authorizes input/auth."""

import json
from unittest.mock import Mock

import pytest

from src.captcha_navigation_flow import FLOW_ENUMS
from src.captcha_navigation_receipt import NAVIGATION_ENUMS, navigation_binding_fields
from src.captcha_verification import ready_target_matches
from tools.test.navigation_flow_fixtures import (
    CHALLENGE,
    FIRST,
    FRAME,
    NEXT,
    TARGET,
    direct,
    prepared,
    request,
    scripted,
)


def fields(solver):
    return navigation_binding_fields(solver, {"href": CHALLENGE})


def test_owned_seed_capture_is_confirmed_before_the_single_navigation():
    solver, sock = prepared(direct())
    assert [m["method"] for m in sock.messages] == [
        "Page.enable",
        "Network.enable",
        "Page.navigate",
    ]
    observed = fields(solver)
    assert observed["navigation_capture"] == "active"
    assert observed["navigation_origin"] == "request"
    assert observed["navigation_transition"] == "http_redirect"
    assert observed["navigation_commit"] == "queryless_challenge"
    assert observed["navigation_flow_loader"] == "match"
    assert observed["navigation_flow_pending"] == "no"
    assert not ready_target_matches({"href": CHALLENGE}, TARGET)
    assert sum(m["method"] == "Page.navigate" for m in sock.messages) == 1


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("scriptInitiated", "script"),
        ("metaTagRefresh", "meta"),
        ("anchorClick", "other"),
    ],
)
def test_new_loader_transition_is_distinct_from_http_redirect(reason, expected):
    solver, _ = prepared(scripted(reason), loader=NEXT)
    observed = fields(solver)
    assert observed["navigation_transition"] == expected
    assert observed["navigation_loader"] == "different"
    assert observed["navigation_flow_loader"] == "match"


@pytest.mark.parametrize(
    "change", ["other_query", "subframe", "fetch", "missing_initial"]
)
def test_unrelated_or_missing_initial_request_is_not_reported_as_the_request(change):
    events = direct()
    if change == "other_query":
        events[0] = request(TARGET + "&page=3")
    elif change == "subframe":
        events[0]["params"]["frameId"] = "PRIVATE_CHILD"
    elif change == "fetch":
        events[0]["params"]["type"] = "Fetch"
    else:
        events.pop(0)
    solver, _ = prepared(events)
    assert fields(solver)["navigation_origin"] != "request"


def test_events_after_navigation_ack_are_observed_by_the_same_command_receiver():
    solver, sock = prepared([request()])
    sock.queue.extend(direct()[1:])
    assert fields(solver)["navigation_transition"] == "http_redirect"
    assert [m["id"] for m in sock.messages] == list(range(1, len(sock.messages) + 1))


@pytest.mark.parametrize("method", ["Page.enable", "Network.enable"])
def test_optional_setup_failure_does_not_prevent_or_repeat_original_navigation(method):
    solver, sock = prepared(direct(), setup_failure=method)
    assert fields(solver)["navigation_capture"] == "unavailable"
    assert sum(m["method"] == "Page.navigate" for m in sock.messages) == 1


@pytest.mark.parametrize("change", ["socket", "disconnected"])
def test_reconnect_does_not_inherit_a_complete_stream(change):
    solver, sock = prepared(direct())
    if change == "socket":
        solver.ws = Mock(connected=True)
        solver._send_cdp = Mock(
            return_value={
                "frameTree": {
                    "frame": {"id": FRAME, "loaderId": FIRST, "url": CHALLENGE}
                }
            }
        )
    else:
        sock.connected = False
    sends_before = len(sock.messages)
    observed = fields(solver)
    if change == "disconnected":
        assert observed == {key: "unavailable" for key in NAVIGATION_ENUMS}
        assert not FLOW_ENUMS.keys() & observed.keys()
        assert len(sock.messages) == sends_before
    else:
        assert observed["navigation_capture"] == "disconnected"


def test_event_cap_and_malformed_events_never_escape_into_command_results():
    solver, sock = prepared(direct() * 30)
    assert fields(solver)["navigation_capture"] == "limited"
    assert len(solver._navigation_trace.events) <= 64
    assert sum(m["method"] == "Page.navigate" for m in sock.messages) == 1


def test_navigation_in_progress_is_not_reported_as_a_completed_commit():
    solver, _ = prepared(scripted()[:-1], loader=FIRST)
    observed = fields(solver)
    assert observed["navigation_commit"] == "request"
    assert observed["navigation_flow_pending"] == "yes"


@pytest.mark.parametrize("owned", [True, False])
def test_detail_and_unowned_calls_keep_existing_no_subscription_contract(owned):
    target = "https://sf-item.taobao.com/sf_item/123.htm" if owned else TARGET
    _, sock = prepared([], target=target, owned=owned)
    assert [m["method"] for m in sock.messages] == ["Page.navigate"]


def test_flow_retains_no_raw_url_headers_or_body_and_is_repr_private():
    events = direct()
    events[0]["params"]["request"].update(
        headers={"Authorization": "PRIVATE_KEY"}, postData="PRIVATE_BODY"
    )
    solver, _ = prepared(events)
    observed = fields(solver)
    assert "PRIVATE" not in json.dumps(observed) + repr(solver._navigation_trace)
    assert "https:" not in repr(solver._navigation_trace.events)
    assert "PRIVATE_KEY" not in repr(solver._navigation_trace.events)
    assert "PRIVATE_BODY" not in repr(solver._navigation_trace.events)


@pytest.mark.parametrize("stop", ["event", "deadline", "checker"])
@pytest.mark.parametrize("method", ["Page.enable", "Network.enable", "Page.navigate"])
def test_setup_and_event_capture_do_not_override_cancel_or_deadline(stop, method):
    from src.captcha_budget import SolveStopped
    from tools.test.test_captcha_target_open_recovery import stopping_budget

    messages = []

    def configure(solver, sock, _):
        trigger = stopping_budget(solver, stop)
        original = sock.send

        def send(raw):
            original(raw)
            messages.append(json.loads(raw))
            if messages[-1]["method"] == method:
                trigger()

        sock.send = send

    with pytest.raises(
        SolveStopped, match="deadline_exceeded" if stop == "deadline" else "cancelled"
    ):
        prepared(direct(), before_prepare=configure)
    assert sum(m["method"] == "Page.navigate" for m in messages) == int(
        method == "Page.navigate"
    )


@pytest.mark.parametrize("malformed", [None, [], {"type": "Document", "request": []}])
def test_malformed_observer_data_cannot_replace_the_actual_navigation_ack(malformed):
    solver, _ = prepared([{"method": "Network.requestWillBeSent", "params": malformed}])
    assert fields(solver)["navigation_capture"] == "unavailable"


def test_receive_failure_invalidates_capture_without_replaying_navigation():
    solver, sock = prepared(direct())
    original = sock.recv
    sock.recv = Mock(side_effect=OSError("fixture transport failure"))
    assert solver._send_cdp("Runtime.evaluate", {"expression": "void 0"}) is None
    sock.queue.clear()
    sock.recv = original
    assert fields(solver)["navigation_capture"] == "unavailable"
    assert sum(m["method"] == "Page.navigate" for m in sock.messages) == 1


def test_flow_enum_projection_survives_the_real_log_and_report_path(monkeypatch):
    import logging

    from src.captcha_navigation_flow import FLOW_ENUMS
    from src.captcha_target_diagnostics import log_target_binding
    from tools import pc2_solver_diagnostics as diagnostics
    from tools.solver_binding_evidence import BINDING_ENUMS
    from tools.solver_observation_evidence import summarize
    from tools.test.test_captcha_target_binding_diagnostics import project

    assert all(
        set(BINDING_ENUMS[key]) == allowed for key, allowed in FLOW_ENUMS.items()
    )
    solver, _ = prepared(scripted(), loader=NEXT)
    observed = fields(solver)
    events = []
    monkeypatch.setattr(diagnostics, "log_event", events.append)
    with diagnostics.solver_attempt_diagnostics():
        log_target_binding(
            logging.getLogger("src.captcha_preflight"),
            "preflight",
            {"href": CHALLENGE},
            TARGET,
            navigation=observed,
        )
    assert len(events) == 1 and events[0]["navigation_transition"] == "script"
    report = summarize(
        [
            project(0, {"kind": "local_solver_start", "target_url": TARGET}),
            project(1, events[0]),
        ]
    )
    saved = report["attempts"][0]["target_binding_events"][0]
    assert (
        saved["navigation_capture"] == "active"
        and saved["navigation_transition"] == "script"
    )
    assert not report["attempts"][0]["verified"]
    assert "PRIVATE" not in json.dumps(report) + json.dumps(events)


@pytest.mark.parametrize("value", [None, [], {}, True, "PRIVATE_MARKER", 12])
def test_untrusted_flow_values_are_revalidated_before_logging_and_persistence(value):
    from src.captcha_navigation_flow import FLOW_ENUMS
    from src.captcha_navigation_receipt import safe_navigation_fields
    from tools.solver_binding_evidence import binding_evidence

    raw = dict.fromkeys(FLOW_ENUMS, value)
    logged = safe_navigation_fields(raw)
    assert all(logged[key] == "unknown" for key in FLOW_ENUMS)
    saved = binding_evidence(raw)
    assert set(saved.values()) == {"unknown"}
    assert "PRIVATE" not in json.dumps(logged) + json.dumps(saved)


def test_optional_capture_preserves_a_raised_stop_without_sending_navigation():
    from src.captcha_budget import SolveStopped

    send = Mock(side_effect=SolveStopped("cancelled"))

    def configure(solver, *_):
        solver._send_cdp = send

    with pytest.raises(SolveStopped, match="cancelled"):
        prepared(direct(), before_prepare=configure)
    send.assert_called_once_with("Page.enable", None)

"""Captcha report admission keeps suppression and solver side-effect order."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def test_native_captcha_report_descriptor():
    from src import captcha_report_handler, server

    handler = object.__new__(server.DataHandler)
    assert handler._post_captcha_report.__self__ is handler
    assert handler._post_captcha_report.__func__ is server._post_captcha_report
    assert server._post_captcha_report.__module__ == captcha_report_handler.__name__
    assert server._CONTEXT._post_captcha_report is server._post_captcha_report


@pytest.fixture
def report(monkeypatch):
    from src import server

    payload = {"node_id": "pc2", "scope": "detail"}
    request = {**payload, "cdp_endpoint": "http://browser.test:9224"}
    values = {
        "_read_json_body": Mock(return_value=(True, payload)),
        "_build_solver_request": Mock(return_value=request),
        "_challenge_scope_for_request": Mock(return_value="detail"),
        "_solver_report_stale_challenge_id": Mock(return_value=None),
        "_solver_report_predates_auth_completion": Mock(return_value=False),
        "_solver_force_reset_report_suppression": Mock(return_value=None),
        "_solver_auth_report_suppression": Mock(return_value=None),
        "_payload_flag": Mock(return_value=False),
        "_payload_manual_only": Mock(return_value=False),
        "_solver_target_requires_manual_only": Mock(return_value=False),
        "_refresh_solver_last_request": Mock(),
        "_payload_force_solver_retry": Mock(return_value=False),
        "_captcha_solver_runtime_status": Mock(return_value={}),
        "_solver_scope_runtime_status": Mock(return_value={}),
        "_solver_cdp_endpoint_is_remote": Mock(return_value=False),
        "_begin_solver_challenge": Mock(),
        "_submit_solver_request": Mock(return_value=True),
        "_set_collection_pause_state": Mock(),
        "_clear_solver_manual_required_pause": Mock(return_value=None),
        "_manual_only_captcha_report_payload": Mock(return_value={"status": "manual"}),
        "_node_solver_blocked_report_payload": Mock(return_value={"status": "blocked"}),
        "RUNTIME": SimpleNamespace(
            recovery=SimpleNamespace(
                snapshot=lambda: SimpleNamespace(challenge_id="active")
            ),
            solver=SimpleNamespace(
                snapshot=lambda: SimpleNamespace(running=False, started_at=0)
            ),
        ),
    }
    for name, value in values.items():
        monkeypatch.setattr(server, name, value)
    handler = SimpleNamespace(
        path="/api/report_captcha", send_json=Mock(), send_error_json=Mock()
    )
    return server, handler, payload, request


@pytest.mark.parametrize(
    "kind",
    [
        "stale_challenge",
        "stale_auth_report",
        "recent_force_reset",
        "recent_auth_complete",
        "blocked",
        "manual",
    ],
)
def test_preflight_rejection_never_refreshes_or_submits(report, kind):
    host, handler, _, _ = report
    if kind == "stale_challenge":
        host._solver_report_stale_challenge_id.return_value = "old"
    elif kind == "stale_auth_report":
        host._solver_report_predates_auth_completion.return_value = True
    elif kind == "recent_force_reset":
        host._solver_force_reset_report_suppression.return_value = {
            "grace_seconds": 10,
            "age_seconds": 8.8,
            "reason": kind,
            "scope": "detail",
        }
    elif kind == "recent_auth_complete":
        host._solver_auth_report_suppression.return_value = {
            "grace_seconds": 10,
            "age_seconds": 11,
            "reason": kind,
            "captured_since_auth": 3,
        }
    elif kind == "blocked":
        host._payload_flag.return_value = True
    else:
        handler.path = "/api/report_manual_captcha?trace=1"
    host._post_captcha_report(handler)
    response = handler.send_json.call_args.args[0]
    assert response["status"] == kind
    if kind == "recent_force_reset":
        assert response["retry_after_seconds"] == 2
    if kind == "recent_auth_complete":
        assert response["retry_after_seconds"] == 0
        assert response["captured_since_auth"] == 3
    host._refresh_solver_last_request.assert_not_called()
    host._begin_solver_challenge.assert_not_called()
    host._submit_solver_request.assert_not_called()


def test_remote_report_begins_then_pauses_without_local_submission(report):
    host, handler, _, request = report
    events = []
    host._solver_cdp_endpoint_is_remote.return_value = True
    host._begin_solver_challenge.side_effect = lambda value: events.append(
        ("begin", value)
    )
    host._set_collection_pause_state.side_effect = lambda *args, **kwargs: (
        events.append(("pause", args, kwargs))
    )
    host._post_captcha_report(handler)
    assert events == [
        ("begin", request),
        ("pause", (True, "captcha_solver"), {"scope": "detail"}),
    ]
    assert handler.send_json.call_args.args[0]["status"] == "deferred_to_node_solver"
    host._submit_solver_request.assert_not_called()


def test_saved_report_uses_replaced_runtime_and_callbacks(report, monkeypatch):
    host, handler, _, _ = report
    saved = host._post_captcha_report
    monkeypatch.setattr(
        host, "_solver_report_stale_challenge_id", lambda payload: "old"
    )
    monkeypatch.setattr(
        host,
        "RUNTIME",
        SimpleNamespace(
            recovery=SimpleNamespace(
                snapshot=lambda: SimpleNamespace(challenge_id="new")
            )
        ),
    )
    saved(handler)
    assert handler.send_json.call_args.args[0]["challenge_id"] == "new"


def test_begin_failure_remains_outside_queue_error_boundary(report):
    host, handler, _, _ = report
    host._begin_solver_challenge.side_effect = RuntimeError("begin failed")
    with pytest.raises(RuntimeError, match="begin failed"):
        host._post_captcha_report(handler)
    handler.send_error_json.assert_not_called()
    host._submit_solver_request.assert_not_called()

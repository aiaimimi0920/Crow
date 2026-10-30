"""Unconfirmed maintenance owns one pending page, not repeated create permission."""

from copy import deepcopy
from unittest.mock import Mock

import pytest

from src.captcha_budget import SolveStopped
from src.captcha_deferral import TargetNavigationUnconfirmed
from src.captcha_solver import CaptchaSolver
from tools import pc2_solver_execution as execution
from tools import pc2_solver_loop_failure as failure
from tools.pc2_solver_state_store import _default_fallback_state
from tools.test.maintenance_deferral_fixtures import CDP, deferred_recovery
from tools.test.pc2_maintenance_budget_fixtures import TARGETS, maintenance_probe


@pytest.mark.parametrize("scope", TARGETS)
@pytest.mark.parametrize("blank", ["", "about:blank"])
def test_lost_navigation_ack_retains_exact_owned_page_across_polls(
    monkeypatch, scope, blank
):
    run = deferred_recovery(monkeypatch, scope, blank)
    first = run.recover()
    pending = first["last_probe_target"]
    assert pending["_target_id"] == "fresh"
    assert pending["_navigation_unconfirmed"] is True
    assert run.events[-1]["reason"] == "target_navigation_unconfirmed"
    opener = run.probe.owners[-1]
    for _ in range(3):
        result = run.recover(pending)
        assert result["last_probe_target"] == pending
        assert run.events[-1]["reason"] == "target_navigation_pending"
        assert run.events[-1]["attempted"] is False
        assert run.events[-1]["opened"] is False
    assert run.probe.put.call_count == len(run.probe.socket.messages) == 1
    assert run.probe.socket.closed
    assert opener._solve_budget is None
    assert not opener.lock.locked()
    run.probe.close_target.assert_not_called()


@pytest.mark.parametrize("scope", TARGETS)
def test_live_request_route_supersedes_pending_navigation(monkeypatch, scope):
    run = deferred_recovery(monkeypatch, scope)
    pending = run.recover()["last_probe_target"]
    run.directory[0]["url"] = TARGETS[scope]
    result = run.recover(pending)
    assert run.events[-1]["reason"] == "request_target_already_present"
    assert result["last_probe_target"]["_target_id"] == "fresh"
    assert not result["last_probe_target"].get("_navigation_unconfirmed")
    assert run.probe.put.call_count == len(run.probe.socket.messages) == 1


@pytest.mark.parametrize(
    "change", ["gone", "foreign_route", "target", "scope", "endpoint", "generation"]
)
def test_pending_page_cannot_block_a_different_request(monkeypatch, change):
    run = deferred_recovery(monkeypatch)
    pending = run.recover()["last_probe_target"]
    if change == "gone":
        run.directory.clear()
    elif change == "foreign_route":
        run.directory[0]["url"] = "https://example.invalid/unrelated"
    elif change == "target":
        run.status["last_request"]["target_url"] = TARGETS["detail"].replace(
            "123", "456"
        )
    elif change == "scope":
        run.status["scope"] = "seed"
        run.status["last_request"]["target_url"] = TARGETS["seed"]
    elif change == "endpoint":
        pending["_target_cdp_endpoint"] = "http://pc1.invalid:9223"
    else:
        run.status["challenge_id"] = "next-generation"
    opened = run.permit_new_open()
    result = run.recover(pending)
    opened.assert_called_once()
    assert result["last_probe_target"]["_target_id"] == "replacement"
    run.probe.close_target.assert_not_called()


@pytest.mark.parametrize(
    "directory",
    [None, {}, "unavailable", [None], [{}], [{"id": "other", "type": "page"}]],
)
def test_invalid_directory_is_not_proof_that_pending_page_disappeared(
    monkeypatch, directory
):
    run = deferred_recovery(monkeypatch)
    pending = run.recover()["last_probe_target"]
    opened = run.permit_new_open()
    monkeypatch.setattr(execution, "fetch_json", lambda *_a, **_k: directory)
    result = run.recover(pending)
    opened.assert_not_called()
    assert result["last_probe_target"] == pending
    assert run.events[-1]["reason"] == "cdp_target_list_unavailable"


@pytest.mark.parametrize("directory", [[None], [{}], [{"id": "other", "type": "page"}]])
def test_rotation_does_not_mutate_pages_after_a_malformed_directory(
    monkeypatch, directory
):
    monkeypatch.setattr(execution, "fetch_json", lambda *_a, **_k: directory)
    opened, closed = Mock(), Mock()
    monkeypatch.setattr(execution, "open_maintenance_target", opened)
    monkeypatch.setattr(CaptchaSolver, "_close_cdp_target", closed)
    result = execution.rotate_failed_challenge_target(CDP, TARGETS["detail"])
    assert result["reason"] == "cdp_target_list_unavailable"
    assert result["opened"] is False
    opened.assert_not_called()
    closed.assert_not_called()


def test_directory_transport_failure_retains_pending_identity(monkeypatch):
    run = deferred_recovery(monkeypatch)
    pending = run.recover()["last_probe_target"]
    opened = run.permit_new_open()
    monkeypatch.setattr(execution, "fetch_json", Mock(side_effect=OSError("offline")))
    assert run.recover(pending)["last_probe_target"] == pending
    opened.assert_not_called()


def test_pending_page_does_not_override_remote_request_owner(monkeypatch):
    run = deferred_recovery(monkeypatch)
    pending = run.recover()["last_probe_target"]
    run.status["last_request"]["node_id"] = "pc1"
    opened = run.permit_new_open()
    result = run.recover(pending)
    opened.assert_not_called()
    assert result["last_probe_target"] is None


def test_pending_probe_is_not_challenge_cleanup_evidence(monkeypatch):
    run = deferred_recovery(monkeypatch)
    pending = run.recover()["last_probe_target"]
    close = Mock()
    monkeypatch.setattr(CaptchaSolver, "_close_cdp_target", close)
    result = execution.close_stale_challenge_probe_target(CDP, pending)
    assert result["attempted"] is False
    close.assert_not_called()


@pytest.mark.parametrize("stop", ["cancelled", "deadline_exceeded"])
def test_stop_during_uncertain_navigation_keeps_original_stop_authority(
    monkeypatch, stop
):
    probe = maintenance_probe(monkeypatch)

    def open_target(solver):
        if stop == "cancelled":
            probe.budget.event.set()
        else:
            probe.now[0] = probe.budget.deadline
        raise TargetNavigationUnconfirmed

    monkeypatch.setattr(CaptchaSolver, "_open_target_tab", open_target)
    with pytest.raises(SolveStopped, match=stop):
        execution.rebuild_missing_challenge_target(CDP, TARGETS["detail"])
    assert probe.owners[-1].last_failure_reason == stop
    probe.close_target.assert_not_called()


def test_rotation_pending_probe_preserves_identity_and_charges_failure_once(
    monkeypatch,
):
    state = _default_fallback_state()
    state.update(scope="detail", challenge_id="owned-generation")
    monkeypatch.setattr(failure, "_load_fallback_state", lambda: deepcopy(state))
    monkeypatch.setattr(
        failure, "_save_fallback_state", lambda value: state.update(value)
    )
    monkeypatch.setattr(failure, "log_event", lambda _: None)
    monkeypatch.setattr(failure, "manual_fallback_enabled", lambda: False)
    browse = Mock()
    monkeypatch.setattr(failure, "maybe_browse_reference_tabs", browse)
    pending = {
        "_target_id": "fresh",
        "_target_url": TARGETS["detail"],
        "_target_cdp_endpoint": CDP,
        "_navigation_unconfirmed": True,
    }
    monkeypatch.setattr(
        failure,
        "rotate_failed_challenge_target",
        Mock(
            return_value={
                "attempted": True,
                "opened": False,
                "closed": 1,
                "reason": "target_navigation_unconfirmed",
                "probe_target": pending,
            }
        ),
    )
    result = failure.record_failed_attempt(
        "http://nas.invalid", CDP, TARGETS["detail"], None
    )
    assert state["consecutive_failures"] == state["slider_attempts"] == 1
    assert result["_challenge_id"] == "owned-generation"
    assert result["_target_id"] == "fresh"
    browse.assert_not_called()


def test_unrelated_blank_page_is_not_pending_request_ownership(monkeypatch):
    run = deferred_recovery(monkeypatch)
    run.directory.append({"id": "unowned-blank", "type": "page", "url": "about:blank"})
    assert run.recover()["last_probe_target"]["_target_id"] == "fresh"
    assert run.probe.put.call_count == 1
    run.probe.close_target.assert_not_called()


@pytest.mark.parametrize("error", [TargetNavigationUnconfirmed, SolveStopped, OSError])
def test_only_owned_maintenance_deferral_is_converted_to_a_result(monkeypatch, error):
    monkeypatch.setattr(execution, "fetch_json", lambda *_a, **_k: [])
    monkeypatch.setattr(execution, "open_maintenance_target", Mock(side_effect=error()))
    with pytest.raises(error):
        execution.rebuild_missing_challenge_target(CDP, TARGETS["detail"])

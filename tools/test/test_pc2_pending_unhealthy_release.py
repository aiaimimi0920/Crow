"""A failed bound detail proof releases waiting, never grants authentication."""

import json
from copy import deepcopy

import pytest

from tools import pc2_solver_state_store as store
from tools.test.pc2_auth_pending_fixtures import BUDGET, CDP, NOW, TARGET, pending_case

__all__ = ["pending_case"]


def test_exhausted_detail_confirmation_releases_only_local_wait(pending_case):
    state, latest, events, retry = pending_case
    before = deepcopy(latest)

    result = retry()

    assert result["pending"] is result["confirmed"] is result["attempted"] is False
    assert result["released"] is True
    assert not result.get("superseded")
    assert (
        result["reason"] == "bound_unhealthy_snapshot_after_auth_confirmation_timeout"
    )
    saved = store._load_fallback_state()
    assert saved == result["state"]
    ack_fields = {
        "last_success_at",
        "auth_complete_pending",
        "auth_completion_id",
        "auth_complete_attempts",
        "auth_complete_next_retry_at",
        "auth_complete_last_error",
        "auth_complete_target_url",
    }
    assert {k: v for k, v in saved.items() if k not in ack_fields} == {
        k: v for k, v in state.items() if k not in ack_fields
    }
    assert {key: saved[key] for key in BUDGET} == BUDGET
    assert saved["auth_completion_id"] is None
    assert latest == before
    assert len(events) == 1
    assert events[0]["kind"] == "auth_confirmation_wait_released"
    assert TARGET not in json.dumps(events)
    assert "owned-receipt" not in json.dumps(events)
    assert "owned-challenge" not in json.dumps(events)


@pytest.mark.parametrize("reset", [False, True])
@pytest.mark.parametrize("confirmed", [None, False])
def test_current_failed_schema_and_pending_reset_remain_supported(
    pending_case, reset, confirmed
):
    _state, latest, _events, retry = pending_case
    latest["scopes"]["detail"]["force_reset_required"] = reset
    if confirmed is not None:
        latest["cookie_snapshot_refresh"]["auth_state_confirmed"] = confirmed
    assert retry()["released"] is True


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("status", "running"),
        ("status", "pending"),
        ("status", "completed"),
        ("status", "busy"),
        ("refreshed", True),
        ("refreshed", None),
        ("retry_queued", True),
        ("retry_queued", None),
        ("next_retry_at_epoch", NOW + 1),
        ("attempts", 2),
        ("attempts", True),
        ("attempts", "3"),
        ("max_attempts", 0),
        ("max_attempts", 3.0),
        ("auth_finalize_requested", False),
        ("auth_state_confirmed", True),
        ("auth_state_confirmed", "false"),
        ("scope", "seed"),
        ("completion_id", "other"),
        ("expected_challenge_id", "other"),
        ("result", {"refreshed": False, "reason": "snapshot_worker_start_failed"}),
        (
            "result",
            {"refreshed": True, "reason": "cookie_snapshot_candidate_unhealthy"},
        ),
    ],
)
def test_incomplete_or_nonterminal_proof_preserves_wait(pending_case, key, value):
    state, latest, events, retry = pending_case
    latest["cookie_snapshot_refresh"][key] = value
    assert retry()["pending"] is True
    assert store._load_fallback_state() == state
    assert events == []


@pytest.mark.parametrize(
    "key",
    [
        "scope",
        "completion_id",
        "expected_challenge_id",
        "status",
        "refreshed",
        "retry_queued",
        "next_retry_at_epoch",
        "attempts",
        "max_attempts",
        "auth_finalize_requested",
        "result",
    ],
)
def test_missing_proof_is_not_a_terminal_receipt(pending_case, key):
    state, latest, _events, retry = pending_case
    latest["cookie_snapshot_refresh"].pop(key)
    assert retry()["pending"] is True
    assert store._load_fallback_state() == state


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("scope", "seed"),
        ("challenge_id", "other"),
        ("paused", False),
        ("manual_only", True),
        ("node_solver_blocked", True),
        ("force_reset_required", None),
        ("operator_paused", True),
        ("last_request", {"scope": "detail", "target_url": TARGET, "node_id": "pc3"}),
        ("last_request", {"scope": "seed", "target_url": TARGET, "node_id": "pc2"}),
        (
            "last_request",
            {"scope": "detail", "target_url": TARGET + "x", "node_id": "pc2"},
        ),
        (
            "last_request",
            {
                "scope": "detail",
                "target_url": TARGET.replace("123", "456"),
                "node_id": "pc2",
            },
        ),
        ("last_request", {}),
        ("last_request", None),
    ],
)
def test_scoped_identity_and_automatic_policy_must_match(pending_case, key, value):
    state, latest, _events, retry = pending_case
    latest["scopes"]["detail"][key] = value
    assert retry()["pending"] is True
    assert store._load_fallback_state() == state


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("scopes", {}),
        ("scopes", None),
        ("scopes", "invalid"),
        ("global_manual_pause_active", True),
        ("global_manual_pause_active", None),
        ("operator_paused", True),
        ("running", True),
        ("queued", True),
        ("nas_solver_active", True),
        ("error", "offline fixture"),
    ],
)
def test_global_or_unknown_control_state_cannot_release(pending_case, key, value):
    state, latest, _events, retry = pending_case
    latest[key] = value
    assert retry()["pending"] is True
    assert store._load_fallback_state() == state


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("scope", "seed"),
        ("scope", None),
        ("challenge_id", None),
        ("auth_completion_id", None),
        ("auth_complete_target_url", TARGET + "x"),
        ("last_success_at", NOW - 119),
        ("manual_pushed", True),
        ("terminal_manual_pending", True),
    ],
)
def test_unbound_young_or_manually_owned_receipt_stays_pending(
    pending_case, key, value
):
    state, _latest, _events, retry = pending_case
    state[key] = value
    assert retry()["pending"] is True
    assert store._load_fallback_state() == state


def test_other_scope_cannot_substitute_for_failed_proof(pending_case):
    state, latest, _events, retry = pending_case
    latest["scopes"]["seed"] = {
        "paused": True,
        "manual_required": True,
        "challenge_id": "unrelated",
    }
    assert retry()["released"] is True
    latest["cookie_snapshot_refresh"]["scope"] = "seed"
    assert retry()["pending"] is True
    assert store._load_fallback_state() == state


def test_modern_empty_scopes_cannot_fall_back_to_legacy(pending_case):
    _state, latest, _events, retry = pending_case
    latest["collection_scopes"] = latest["scopes"]
    latest["scopes"] = {}
    assert retry()["pending"] is True


def test_explicit_node_identity_keeps_existing_endpoint_alias_policy(pending_case):
    _state, latest, _events, retry = pending_case
    latest["scopes"]["detail"]["last_request"]["cdp_endpoint"] = "http://pc2.test:9224"
    assert retry()["released"] is True
    assert retry(expected_node_id="pc3")["pending"] is True
    assert retry(expected_node_id=None, cdp_endpoint="")["pending"] is True
    latest["scopes"]["detail"]["last_request"]["cdp_endpoint"] = CDP
    assert retry(expected_node_id=None)["released"] is True


def test_automatic_switch_off_does_not_use_failure_release(monkeypatch, pending_case):
    _state, _latest, _events, retry = pending_case
    monkeypatch.setenv("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", "0")
    assert retry()["pending"] is True


@pytest.mark.parametrize("field", ["scopes", "collection_scopes"])
def test_bound_challenge_suffix_uses_canonical_target(pending_case, field):
    state, latest, _events, retry = pending_case
    state["auth_complete_target_url"] = TARGET + "/_____tmd_____/punish?opaque=fixture"
    if field == "collection_scopes":
        latest[field] = latest.pop("scopes")
    assert retry()["released"] is True


def test_unknown_running_or_scoped_running_cannot_release(pending_case):
    _state, latest, _events, retry = pending_case
    latest.pop("running")
    assert retry()["pending"] is True
    latest["running"] = False
    latest["scopes"]["detail"]["running"] = True
    assert retry()["pending"] is True


def test_existing_manual_timeout_is_not_reclassified(pending_case):
    _state, latest, events, retry = pending_case
    latest["scopes"]["detail"]["manual_required"] = True
    result = retry()
    assert result["superseded"] is True
    assert not result.get("released")
    assert result["reason"] == "active_challenge_after_auth_confirmation_timeout"
    assert events == []

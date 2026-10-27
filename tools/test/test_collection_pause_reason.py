"""A paused scope is not evidence that a solver is actively running."""

import copy

import pytest

from tools import (
    detail_worker,
    detail_worker_policy,
    seed_collector,
    seed_collector_auth,
)

OWNERS = (
    (detail_worker_policy, "detail"),
    (detail_worker, "detail"),
    (seed_collector_auth, "seed"),
    (seed_collector, "seed"),
)


def status_for_scope(scope, layout, **state):
    # A different scope can be running without this scope being active.
    payload = {
        "paused": True,
        "captcha_solver": {"running": True, "paused": True},
    }
    scoped = {"paused": True, "manual_required": False, **state}
    if layout == "top":
        payload["collection_scopes"] = {scope: scoped}
    else:
        payload["captcha_solver"][layout] = {scope: scoped}
    return payload


@pytest.mark.parametrize("owner,scope", OWNERS)
@pytest.mark.parametrize("layout", ["top", "collection_scopes", "scopes"])
@pytest.mark.parametrize("last_status", [None, "queued", "failed", "completed"])
def test_paused_scope_without_running_status_is_not_reported_as_running(
    owner, scope, layout, last_status
):
    payload = status_for_scope(scope, layout, last_status=last_status)
    before = copy.deepcopy(payload)
    result = owner._normalize_collection_pause_state(payload, scope=scope)
    assert result["paused"] is True
    assert result["captcha_solver"]["running"] is False
    assert result["reason"] == "collection_paused"
    assert result["scope"] == scope
    assert payload == before


@pytest.mark.parametrize("owner,scope", OWNERS)
@pytest.mark.parametrize(
    "state,reason,paused,running",
    [
        ({"last_status": "running"}, "captcha_solver_running", True, True),
        (
            {"last_status": "running", "manual_required": True},
            "captcha_solver_manual_required",
            True,
            True,
        ),
        (
            {"last_status": "failed", "manual_required": True},
            "captcha_solver_manual_required",
            True,
            False,
        ),
        ({"paused": False, "last_status": "completed"}, None, False, False),
    ],
)
def test_existing_running_manual_and_clear_states_are_preserved(
    owner, scope, state, reason, paused, running
):
    result = owner._normalize_collection_pause_state(
        status_for_scope(scope, "top", **state), scope=scope
    )
    assert result["reason"] == reason
    assert result["paused"] is paused
    assert result["captcha_solver"]["running"] is running


def test_detail_worker_generic_pause_reason_survives_safe_batch_projection():
    from tools.detail_worker_observation import batch_observation

    result = batch_observation(
        [{"decision": "detail_collection_paused", "reason": "collection_paused"}],
        elapsed_seconds=0,
    )
    assert result["reason_counts"] == {"collection_paused": 1}

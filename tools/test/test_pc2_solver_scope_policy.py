"""Native scope policy contracts retained by the solver facade."""

import pytest

from tools import pc2_solver_scope_policy as policy


def test_facade_and_scope_publish_native_policy_functions() -> None:
    from tools import pc2_local_solver, pc2_solver_scope

    for name in policy.__all__:
        original = getattr(policy, name)
        assert getattr(pc2_local_solver, name) is original
        assert getattr(pc2_solver_scope, name) is original
        assert original.__globals__ is vars(policy)


def test_scope_projection_breaks_ties_without_mutating_input() -> None:
    detail_request = {"node_id": "pc2"}
    aggregate = {
        "running": True,
        "collection_scopes": {
            "seed": {"challenge_id": "seed-1", "first_seen_epoch": 0},
            "detail": {
                "challenge_id": "detail-1",
                "first_seen_epoch": 0,
                "paused": True,
                "last_request": detail_request,
            },
        },
    }

    projected = policy.select_solver_scope_status(aggregate)

    assert projected["scope"] == "detail"
    assert projected["challenge_id"] == "detail-1"
    assert projected["running"] is True
    assert projected["last_request"] == detail_request
    assert projected["last_request"] is not detail_request
    assert "scope" not in aggregate
    assert policy.select_solver_scope_status(aggregate, "seed-1")["scope"] == "seed"


def test_invalid_scope_timestamp_still_surfaces_protocol_error() -> None:
    with pytest.raises(ValueError):
        policy.select_solver_scope_status(
            {"scopes": {"seed": {"challenge_id": "seed-1", "first_seen_epoch": "bad"}}}
        )

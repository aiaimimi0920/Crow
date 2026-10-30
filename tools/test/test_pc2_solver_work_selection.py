"""Pure arbitration regressions: scope eligibility is not global authority."""

from copy import deepcopy

import pytest

from tools.pc2_solver_scope_policy import select_solver_scope_status
from tools.pc2_solver_state_store import _default_fallback_state
from tools.pc2_solver_work_selection import select_solver_work_status
from tools.test.test_pc2_solver_work_selection_loop import scoped_status

CDP = "http://127.0.0.1:9223"


@pytest.fixture
def inputs(monkeypatch):
    monkeypatch.setenv("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", "1")
    state = _default_fallback_state()
    state.update(challenge_id="seed-one", scope="seed")
    return scoped_status(), state


def select(inputs):
    return select_solver_work_status(*inputs, CDP, "pc2")


def test_selects_work_but_preserves_stable_receipt_projection_and_all_scopes(inputs):
    before = deepcopy(inputs)
    result = select(inputs)
    assert result["scope"] == "detail"
    assert result["challenge_id"] == "detail-one"
    assert result["running"] is False
    assert result["scopes"] == inputs[0]["scopes"]
    assert inputs == before
    assert select_solver_scope_status(inputs[0], "seed-one")["scope"] == "seed"


def test_initial_empty_fallback_can_find_automatic_work(inputs):
    inputs[1].update(challenge_id=None, scope=None)
    assert select(inputs)["scope"] == "detail"


@pytest.mark.parametrize("latch", [True, None, "false"])
def test_unbound_legacy_manual_latch_cannot_be_reset_by_switching(inputs, latch):
    inputs[1].update(
        challenge_id=None, scope=None, manual_pushed=latch, consecutive_failures=7
    )
    assert select(inputs)["scope"] == "seed"


def test_automatic_work_remains_stable_after_switch(inputs):
    inputs[1].update(challenge_id="detail-one", scope="detail")
    assert select(inputs)["scope"] == "detail"


def test_symmetric_manual_detail_does_not_starve_seed(inputs):
    status, state = inputs
    status.update(scope="detail")
    for scope in ("seed", "detail"):
        status["scopes"][scope].update(
            manual_only=scope == "detail", manual_required=scope == "detail"
        )
    state.update(challenge_id="detail-one", scope="detail")
    assert select(inputs)["scope"] == "seed"


@pytest.mark.parametrize(
    "key", ["running", "queued", "nas_solver_active", "force_unlock_flag_exists"]
)
@pytest.mark.parametrize("value", [True, None, "false", 0])
def test_global_gates_require_explicit_false(inputs, key, value):
    inputs[0][key] = value
    assert select(inputs)["scope"] == "seed"


@pytest.mark.parametrize(
    "key", ["running", "queued", "nas_solver_active", "force_unlock_flag_exists"]
)
def test_missing_global_gate_is_not_idle(inputs, key):
    del inputs[0][key]
    assert select(inputs)["scope"] == "seed"


def test_explicit_server_mirror_proof_allows_only_the_existing_scoped_switch(inputs):
    inputs[0].update(force_unlock_flag_exists=True, global_manual_pause_active=False)
    assert select(inputs)["scope"] == "detail"


@pytest.mark.parametrize("value", [True, None, "false", 0])
def test_unknown_or_active_global_manual_semantics_cannot_override_raw_gate(
    inputs, value
):
    inputs[0].update(force_unlock_flag_exists=True, global_manual_pause_active=value)
    assert select(inputs)["scope"] == "seed"


def test_new_global_manual_gate_cannot_be_overridden_by_stale_raw_false(inputs):
    inputs[0].update(force_unlock_flag_exists=False, global_manual_pause_active=True)
    assert select(inputs)["scope"] == "seed"


@pytest.mark.parametrize(
    "changes",
    [
        {"operator_paused": True},
        {"operator_paused": None},
        {"pause_reason": "operator"},
        {"pause_reason": None},
        {"pause_reason": "unknown"},
        {"error": "unavailable"},
        {"scope": None},
        {"scope": "other"},
    ],
)
def test_operator_or_legacy_global_manual_wait_is_not_scoped_work(inputs, changes):
    inputs[0].update(changes)
    assert select(inputs)["scope"] == "seed"


def test_unscoped_manual_only_cannot_be_overridden(inputs):
    inputs[0]["scope"] = "detail"
    assert select(inputs)["scope"] == "seed"


@pytest.mark.parametrize(
    "key",
    ["auth_complete_pending", "collection_resume_pending", "terminal_manual_pending"],
)
@pytest.mark.parametrize("value", [True, None, "false", 0])
def test_pending_obligations_and_unknowns_cannot_be_discarded(inputs, key, value):
    inputs[1][key] = value
    assert select(inputs)["scope"] == "seed"


@pytest.mark.parametrize(
    "changes",
    [
        {"solver_cooldown_until": 1},
        {"solver_cooldown_until": 9999999999},
        {"solver_cooldown_reason": "repeated_solver_failures"},
        {"slider_attempt_started_at": 1},
        {"node_solver_blocked_reported": True},
        {"node_solver_blocked_report_attempts": 1},
        {"node_solver_blocked_report_next_retry_at": 1},
        {"challenge_id": "other"},
        {"scope": "other"},
    ],
)
def test_cooldown_report_ack_and_generation_obligations_remain_bound(inputs, changes):
    inputs[1].update(changes)
    assert select(inputs)["scope"] == "seed"


@pytest.mark.parametrize("scope", ["seed", "detail"])
@pytest.mark.parametrize(
    "key,value",
    [
        ("paused", False),
        ("paused", None),
        ("manual_only", None),
        ("node_solver_blocked", True),
        ("node_solver_blocked", None),
        ("force_reset_required", True),
        ("force_reset_required", None),
    ],
)
def test_only_complete_scoped_states_can_participate(inputs, scope, key, value):
    inputs[0]["scopes"][scope][key] = value
    assert select(inputs)["scope"] == "seed"


@pytest.mark.parametrize("scope", ["seed", "detail"])
@pytest.mark.parametrize(
    "request_payload",
    [
        None,
        {},
        {
            "node_id": "other",
            "target_url": "https://sf-item.taobao.com/sf_item/123.htm",
        },
        {"node_id": "pc2", "target_url": "https://unrelated.test/"},
        {
            "node_id": "pc2",
            "target_url": "https://sf-item.taobao.com/sf_item/123.htm",
            "scope": "other",
        },
    ],
)
def test_both_manual_and_automatic_scope_require_owned_target_identity(
    inputs, scope, request_payload
):
    inputs[0]["scopes"][scope]["last_request"] = request_payload
    assert select(inputs)["scope"] == "seed"


def test_explicit_foreign_owner_wins_over_matching_loopback(inputs):
    inputs[0]["scopes"]["detail"]["last_request"].update(
        node_id="pc3", cdp_endpoint=CDP
    )
    assert select(inputs)["scope"] == "seed"


def test_legacy_endpoint_ownership_is_preserved(inputs):
    inputs[0]["scopes"]["detail"]["last_request"].update(node_id=None, cdp_endpoint=CDP)
    assert select(inputs)["scope"] == "detail"


def test_disabled_automatic_solver_does_not_create_eligible_work(inputs, monkeypatch):
    monkeypatch.setenv("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", "0")
    assert select(inputs)["scope"] == "seed"


@pytest.mark.parametrize(
    "key,value",
    [("manual_required", True), ("manual_only", True), ("challenge_id", None)],
)
def test_manual_or_missing_candidate_is_not_scheduled(inputs, key, value):
    inputs[0]["scopes"]["detail"][key] = value
    assert select(inputs)["scope"] == "seed"


@pytest.mark.parametrize("value", [{}, None, [], "unknown"])
def test_explicit_empty_modern_scopes_do_not_revive_legacy_candidates(inputs, value):
    status, _state = inputs
    status["collection_scopes"] = status["scopes"]
    status["scopes"] = value
    assert select(inputs)["scope"] == "seed"


def test_legacy_scoped_status_uses_same_admission(inputs):
    status, _state = inputs
    status["collection_scopes"] = status.pop("scopes")
    assert select(inputs)["scope"] == "detail"


def test_singleton_and_unknown_scopes_keep_existing_projection(inputs):
    status, state = inputs
    del status["scopes"]
    status.update(challenge_id="legacy", last_request={"node_id": "pc2"})
    assert select(inputs) == select_solver_scope_status(status, state["challenge_id"])

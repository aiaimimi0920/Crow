"""Snapshot summaries are callable directly, with no server-global injection."""

import json

import pytest

from src import server_hybrid_context as context
from src import server_hybrid_history as history
from src import server_hybrid_lifecycle as lifecycle
from src import server_hybrid_runtime as runtime


@pytest.fixture(params=["native", "facade"])
def summaries(request):
    if request.param == "native":
        return history, lifecycle
    from src import server

    return server, server


def test_history_reads_recent_window_and_refreshes_replaced_snapshot(
    tmp_path, summaries
):
    history_owner, _ = summaries
    root = tmp_path / "avm"
    root.mkdir()
    path = root / "hybrid_seed_collection_runtime_history.jsonl"
    entries = [
        {"decision_counts": {"browserless_success": 99}},
        {
            "generated_at": "2026-09-24T00:00:00Z",
            "decision_counts": {
                "browserless_success": "2",
                "browser_fallback_required": 1,
                "invalid_count": "unknown",
            },
            "reason_counts": {"challenge_detected": 1},
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in entries), encoding="utf-8")

    read = history_owner._hybrid_collection_runtime_history_summary
    summary = read(tmp_path, limit=1)
    assert summary["entry_count"] == 2
    assert summary["recent_runs"] == 1
    assert summary["recent_browserless_success_count"] == 2
    assert summary["recent_browserless_success_rate"] == pytest.approx(2 / 3)
    assert summary["recent_top_fallback_reason"] == "challenge_detected"
    summary["recent_decision_counts"]["browserless_success"] = 200
    assert read(tmp_path, limit=1)["recent_browserless_success_count"] == 2

    replacement = root / "replacement.jsonl"
    replacement.write_text(
        json.dumps({"decision_counts": {"browserless_success": 7}}),
        encoding="utf-8",
    )
    replacement.replace(path)
    assert read(tmp_path)["recent_browserless_success_count"] == 7
    path.write_text("{incomplete", encoding="utf-8")
    assert read(tmp_path)["available"] is False
    assert path.read_bytes() == b"{incomplete"


def test_lifecycle_preserves_escalation_priority_and_runtime_hint(summaries):
    _, owner = summaries
    runtime = {"available": True, "operator_action_hint": "inspect current backlog"}
    state = owner._hybrid_collection_lifecycle_state_summary(
        runtime,
        {"policy_status": "steady_hybrid"},
        {"window_open": True},
        {
            "recent_high_priority_unresolved_count": "2",
            "top_recent_unresolved_priority": "high",
        },
    )
    assert state["lifecycle_state"] == "escalated"
    assert state["suggested_mode"] == "browser"
    assert state["active_high_priority_unresolved_count"] == 2
    assert state["operator_action_hint"] == "inspect current backlog"
    consistency = owner._hybrid_collection_action_hint_consistency_summary(
        runtime, state
    )
    assert consistency["consistency_status"] == "aligned"
    intervention = owner._hybrid_collection_operator_intervention_policy_summary(
        state, consistency, {}, {}
    )
    assert intervention["intervention_required"] is True
    assert intervention["intervention_priority"] == "high"
    assert (
        intervention["intervention_reason"]
        == "high_priority_unresolved_escalation_backlog"
    )


def test_missing_signals_do_not_claim_a_ready_collection(summaries):
    _, owner = summaries
    state = owner._hybrid_collection_lifecycle_state_summary({}, {}, {}, {})
    assert state["available"] is False
    assert state["lifecycle_state"] == "unknown"
    assert state["recommended_follow_up"] == "collect_runtime_history"
    intervention = owner._hybrid_collection_operator_intervention_policy_summary(
        state, {}, {}, {}
    )
    assert intervention["available"] is False
    assert intervention["intervention_status"] == "unknown"


@pytest.fixture(params=["native", "facade"])
def snapshot_owners(request):
    if request.param == "native":
        return runtime, context
    from src import server

    return server, server


def test_challenge_metrics_combine_current_and_history_snapshots(
    tmp_path, snapshot_owners
):
    owner, _ = snapshot_owners
    root = tmp_path / "avm"
    root.mkdir()
    (root / "hybrid_seed_collection_runtime.json").write_text(
        json.dumps(
            {
                "decision_counts": {
                    "browserless_success": 2,
                    "browser_fallback_required": 1,
                },
                "reason_counts": {"challenge_detected": 1},
            }
        ),
        encoding="utf-8",
    )
    (root / "hybrid_seed_collection_runtime_history.jsonl").write_text(
        json.dumps(
            {
                "decision_counts": {
                    "browserless_success": 3,
                    "browser_fallback_required": 1,
                },
                "reason_counts": {"challenge_detected": 2},
            }
        ),
        encoding="utf-8",
    )
    summary = owner._hybrid_collection_challenge_metrics_summary(tmp_path)
    assert summary["current_browserless_attempt_count"] == 3
    assert summary["current_challenge_hit_rate"] == pytest.approx(1 / 3)
    assert summary["recent_browserless_attempt_count"] == 4
    assert summary["recent_challenge_hit_rate"] == 0.5


def test_pc1_snapshot_uses_shared_root_and_aware_elapsed_time(
    tmp_path, snapshot_owners
):
    owner, _ = snapshot_owners
    root = tmp_path / "secrets"
    root.mkdir()
    path = root / "pc1-auth-auto-resume-state.json"
    original = json.dumps(
        {
            "started_at": "2026-05-19T02:00:00+02:00",
            "completed_at": "2026-05-19T00:01:30Z",
            "status": "completed",
            "poll_seconds": -1,
        }
    ).encode()
    path.write_bytes(original)
    summary = owner._pc1_auth_auto_resume_state_summary(tmp_path / "datas")
    assert summary["available"] is True
    assert summary["wait_elapsed_seconds"] == 90
    assert summary["poll_seconds"] == 0
    assert path.read_bytes() == original


def test_escalation_overview_preserves_unknown_duration(snapshot_owners):
    _, owner = snapshot_owners
    overview = (
        owner._hybrid_collection_operator_unresolved_escalation_window_overview_fields(
            {
                "window_open": True,
                "last_escalation_policy_status": "escalate_repeated_repin",
                "current_window_duration_seconds": -1,
                "current_window_duration_minutes": -1,
            }
        )
    )
    assert overview["hybrid_collection_unresolved_escalation_window_open"] is True
    assert (
        overview["hybrid_collection_unresolved_escalation_policy_status"]
        == "escalate_repeated_repin"
    )
    assert overview["hybrid_collection_unresolved_escalation_duration_seconds"] is None
    assert overview["hybrid_collection_unresolved_escalation_duration_minutes"] is None

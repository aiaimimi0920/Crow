"""Hybrid policy consumers work with native owners and the public server facade."""

import json

import pytest

from src import server_hybrid_escalation as escalation
from src import server_hybrid_events as events
from src import server_hybrid_operator_summary as operator
from src import server_hybrid_policy as policy


@pytest.fixture(params=["native", "facade"])
def owners(request):
    if request.param == "native":
        return events, escalation, operator, policy
    from src import server

    return server, server, server, server


def test_recent_event_window_preserves_escalation_changes(tmp_path, owners):
    event_owner, escalation_owner, _, _ = owners
    root = tmp_path / "avm"
    root.mkdir()
    path = root / "hybrid_seed_operator_escalation_events.jsonl"
    rows = [
        {"operator_escalation_source": "ignored_older_source"},
        {
            "generated_at": "2026-09-24T00:00:00Z",
            "operator_escalation_source": "recovery_policy",
            "escalation_kind": "operator_required",
        },
        {
            "generated_at": "2026-09-24T00:01:00Z",
            "operator_escalation_source": "lifecycle_high_priority_backlog",
            "operator_escalation_audit_message": "Inspect outstanding jobs",
            "escalation_kind": "operator_required",
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    summary = event_owner._hybrid_collection_operator_escalation_event_summary(
        tmp_path, limit=2
    )
    assert summary["entry_count"] == 3
    assert summary["recent_event_count"] == 2
    assert summary["recent_escalation_kind_counts"] == {"operator_required": 2}
    assert (
        "ignored_older_source"
        not in summary["recent_operator_escalation_source_counts"]
    )
    trend = event_owner._hybrid_collection_operator_escalation_event_trend_summary(
        tmp_path, limit=2
    )
    stability = (
        escalation_owner._hybrid_collection_operator_escalation_event_stability_summary(
            trend
        )
    )
    assert stability["stability_status"] == "source_recently_shifted"
    assert stability["stability_severity"] == "high"
    assert stability["previous_operator_escalation_source"] == "recovery_policy"
    assert stability["last_source_change_at"] == "2026-09-24T00:01:00Z"


def test_repeated_challenge_repin_overrides_healthy_hybrid_guidance(tmp_path, owners):
    _, _, _, owner = owners
    result = owner._hybrid_collection_recovery_policy(
        tmp_path,
        {
            "last_decision": "browser_fallback_required",
            "last_reason": "challenge_detected",
        },
        {"available": True, "recent_browserless_success_rate": 0.95},
        {"recommended_mode": "hybrid", "priority": "info"},
        {"recent_switch_count": 4, "top_target_mode": "browser"},
        {"recent_transition_kind_counts": {"pin_released": 2, "pin_activated": 2}},
    )
    assert result["policy_status"] == "escalate_repeated_repin"
    assert result["priority"] == "high"
    assert result["effective_recommended_mode"] == "browser"
    assert result["mode_pin_active"] is True


def test_current_guidance_drives_digest_and_public_overview(owners):
    _, _, operator_owner, policy_owner = owners
    guidance = operator_owner._hybrid_collection_operator_final_guidance_summary(
        {"available": True, "intervention_status": "ready", "suggested_mode": "hybrid"},
        {
            "available": True,
            "stability_status": "escalating",
            "stability_action_hint": "switch to browser",
        },
    )
    assert guidance["suggested_mode"] == "browser"
    digest = operator_owner._hybrid_collection_operator_digest_summary(
        {"available": True, "intervention_status": "ready"}, {}, guidance, {}
    )
    overview = policy_owner._hybrid_collection_operator_digest_overview_fields(digest)
    assert (
        overview["hybrid_collection_operator_digest_status"] == "intervention_required"
    )
    assert overview["hybrid_collection_operator_digest_priority"] == "high"
    assert overview["hybrid_collection_operator_digest_message"] == (
        "Escalating intervention: switch to browser."
    )


def test_missing_event_history_remains_unavailable(tmp_path, owners):
    event_owner, escalation_owner, _, policy_owner = owners
    trend = event_owner._hybrid_collection_operator_escalation_event_trend_summary(
        tmp_path
    )
    assert trend["available"] is False
    stability = (
        escalation_owner._hybrid_collection_operator_escalation_event_stability_summary(
            trend
        )
    )
    assert stability["available"] is False
    assert stability["stability_status"] == "unknown"
    guidance = policy_owner._hybrid_collection_strategy_guidance({}, {})
    assert guidance["guidance_status"] == "no_history_available"
    assert guidance["recommended_actions"] == ["collect_more_hybrid_runtime_history"]

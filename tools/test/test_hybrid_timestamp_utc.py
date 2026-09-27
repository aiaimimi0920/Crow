import json
from datetime import datetime, timezone

import pytest

from src import (
    server,
    server_hybrid_escalation,
    server_hybrid_operator_summary,
    server_hybrid_policy,
)


@pytest.fixture(params=["native", "facade"])
def summaries(request):
    if request.param == "native":
        return server_hybrid_escalation, server_hybrid_operator_summary
    return server, server


def test_hybrid_timestamp_parser_normalizes_legacy_and_iso_values():
    expected = datetime(2026, 5, 19, 0, 40, tzinfo=timezone.utc)
    assert server._parse_utc_timestamp("2026-05-19 00:40:00") == expected
    assert server._parse_utc_timestamp("2026-05-19T00:40:00Z") == expected
    assert server._parse_utc_timestamp("2026-05-19T02:40:00+02:00") == expected
    assert server._parse_utc_timestamp("not-a-timestamp") is None


def test_unresolved_hybrid_window_uses_aware_utc_duration(monkeypatch, summaries):
    monkeypatch.setattr(
        server_hybrid_escalation,
        "_utc_now",
        lambda: datetime(2026, 5, 19, 0, 2, tzinfo=timezone.utc),
    )
    escalation_owner, _ = summaries
    summary = escalation_owner._hybrid_collection_unresolved_escalation_window_summary(
        {
            "available": True,
            "last_event_at": "2026-05-19T00:00:00Z",
            "top_policy_status": "escalate_repeated_repin",
        },
        {"available": False},
    )
    assert summary["window_open"] is True
    assert summary["current_window_duration_seconds"] == 120
    assert summary["current_window_duration_minutes"] == 2.0


def test_recovery_latency_accepts_mixed_aware_iso_timestamps(tmp_path, summaries):
    avm_root = tmp_path / "avm"
    avm_root.mkdir()
    (avm_root / "hybrid_seed_operator_escalation_events.jsonl").write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19T00:30:00+00:00",
                "policy_status": "escalate_repeated_repin",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (avm_root / "hybrid_seed_operator_escalation_recovery_events.jsonl").write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19T00:31:30Z",
                "from_policy_status": "escalate_repeated_repin",
                "to_policy_status": "steady_hybrid",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    _, operator_owner = summaries
    summary = operator_owner._hybrid_collection_recovery_latency_summary(tmp_path)

    assert summary["available"] is True
    assert summary["matched_escalation_at"] == "2026-05-19T00:30:00+00:00"
    assert summary["last_recovery_latency_seconds"] == 90
    assert summary["last_recovery_latency_minutes"] == 1.5


@pytest.mark.parametrize(
    ("escalated_at", "recovered_at", "window_open"),
    [
        ("2026-05-19T02:00:00+02:00", "2026-05-19T00:01:00Z", False),
        ("2026-05-19T00:02:00Z", "2026-05-19T02:01:00+02:00", True),
        ("2026-05-19T02:00:00+02:00", "2026-05-19T00:00:00Z", False),
    ],
)
def test_escalation_window_compares_instants_across_offsets(
    summaries, escalated_at, recovered_at, window_open
):
    owner, _ = summaries
    summary = owner._hybrid_collection_unresolved_escalation_window_summary(
        {"available": True, "last_event_at": escalated_at},
        {"available": True, "last_event_at": recovered_at},
    )
    assert summary["window_open"] is window_open
    assert summary["window_status"] == ("open" if window_open else "closed")


@pytest.mark.parametrize(
    "policy_owner", [server_hybrid_policy, server], ids=["native", "facade"]
)
@pytest.mark.parametrize("history_count", [0, 2])
def test_retrial_budget_counts_attempts_after_offset_release(
    tmp_path, policy_owner, history_count
):
    if history_count:
        root = tmp_path / "avm"
        root.mkdir()
        (root / "hybrid_seed_collection_runtime_history.jsonl").write_text(
            json.dumps(
                {
                    "generated_at": "2026-05-19T00:01:00Z",
                    "decision_counts": {"browserless_success": history_count},
                }
            ),
            encoding="utf-8",
        )
    summary = policy_owner._hybrid_collection_recovery_policy(
        tmp_path,
        {
            "generated_at": "2026-05-19T00:01:00Z",
            "last_decision": "browserless_success",
        },
        {"available": True, "recent_browserless_success_rate": 0.9},
        {"recommended_mode": "hybrid"},
        {"recent_switch_count": 1, "top_target_mode": "browser"},
        {
            "last_transition_kind": "pin_released",
            "last_transition_at": "2026-05-19T02:00:00+02:00",
            "last_to_policy_status": "allow_hybrid_retrial",
        },
    )
    assert summary["hybrid_retrial_attempts_used"] == (history_count or 1)
    assert summary["hybrid_retrial_budget_remaining"] == 0

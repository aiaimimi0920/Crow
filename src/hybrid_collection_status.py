"""Build hybrid summaries and their public overview from one status pass."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.collection_status_snapshots import (
    _hybrid_collection_runtime_summary,
)
from src.server_hybrid_escalation import (
    _hybrid_collection_escalation_priority_mix_trend_summary,
    _hybrid_collection_escalation_resolution_trend_summary,
    _hybrid_collection_operator_escalation_event_stability_summary,
    _hybrid_collection_operator_escalation_recovery_event_summary,
    _hybrid_collection_operator_intervention_event_summary,
    _hybrid_collection_unresolved_escalation_window_summary,
)
from src.server_hybrid_escalation_overview import (
    _hybrid_collection_operator_action_hint_consistency_overview_fields,
    _hybrid_collection_operator_escalation_event_stability_overview_fields,
    _hybrid_collection_operator_escalation_event_trend_overview_fields,
    _hybrid_collection_operator_escalation_priority_mix_trend_overview_fields,
    _hybrid_collection_operator_escalation_recovery_event_overview_fields,
    _hybrid_collection_operator_escalation_resolution_trend_overview_fields,
    _hybrid_collection_operator_lifecycle_state_overview_fields,
    _hybrid_collection_operator_recovery_latency_overview_fields,
    _hybrid_collection_operator_unresolved_escalation_window_overview_fields,
)
from src.server_hybrid_events import (
    _hybrid_collection_mode_switch_event_summary,
    _hybrid_collection_operator_digest_stability_summary,
    _hybrid_collection_operator_escalation_event_summary,
    _hybrid_collection_operator_escalation_event_trend_summary,
    _hybrid_collection_operator_intervention_trend_summary,
    _hybrid_collection_recovery_policy_event_summary,
)
from src.server_hybrid_history import (
    _hybrid_collection_action_hint_trend_summary,
    _hybrid_collection_operator_digest_trend_summary,
    _hybrid_collection_operator_final_guidance_stability_summary,
    _hybrid_collection_operator_final_guidance_trend_summary,
    _hybrid_collection_runtime_history_summary,
)
from src.server_hybrid_lifecycle import (
    _hybrid_collection_action_hint_consistency_summary,
    _hybrid_collection_lifecycle_state_summary,
    _hybrid_collection_operator_intervention_policy_summary,
    _hybrid_collection_operator_intervention_stability_summary,
)
from src.server_hybrid_operator_summary import (
    _hybrid_collection_operator_digest_summary,
    _hybrid_collection_operator_final_guidance_summary,
    _hybrid_collection_recovery_latency_summary,
)
from src.server_hybrid_overview import (
    _hybrid_collection_operator_action_hint_trend_overview_fields,
    _hybrid_collection_operator_digest_overview_fields,
    _hybrid_collection_operator_digest_stability_overview_fields,
    _hybrid_collection_operator_digest_trend_overview_fields,
    _hybrid_collection_operator_escalation_event_overview_fields,
    _hybrid_collection_operator_final_guidance_overview_fields,
    _hybrid_collection_operator_final_guidance_stability_overview_fields,
    _hybrid_collection_operator_final_guidance_trend_overview_fields,
    _hybrid_collection_operator_guidance_overview_fields,
    _hybrid_collection_operator_history_overview_fields,
    _hybrid_collection_operator_intervention_event_overview_fields,
    _hybrid_collection_operator_intervention_policy_overview_fields,
    _hybrid_collection_operator_intervention_stability_overview_fields,
    _hybrid_collection_operator_intervention_trend_overview_fields,
    _hybrid_collection_operator_mode_switch_overview_fields,
    _hybrid_collection_operator_overview_fields,
    _hybrid_collection_operator_recovery_policy_event_overview_fields,
    _hybrid_collection_operator_recovery_policy_overview_fields,
)
from src.server_hybrid_policy import (
    _hybrid_collection_recovery_policy,
    _hybrid_collection_strategy_guidance,
)


def _hybrid_collection_status(data_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    hybrid_collection_runtime_summary = _hybrid_collection_runtime_summary(data_root)
    hybrid_collection_runtime_history_summary = (
        _hybrid_collection_runtime_history_summary(data_root)
    )
    hybrid_collection_action_hint_trend_summary = (
        _hybrid_collection_action_hint_trend_summary(data_root)
    )
    hybrid_collection_operator_final_guidance_trend_summary = (
        _hybrid_collection_operator_final_guidance_trend_summary(data_root)
    )
    hybrid_collection_operator_final_guidance_stability_summary = (
        _hybrid_collection_operator_final_guidance_stability_summary(
            hybrid_collection_operator_final_guidance_trend_summary,
        )
    )
    hybrid_collection_operator_intervention_trend_summary = (
        _hybrid_collection_operator_intervention_trend_summary(data_root)
    )
    hybrid_collection_mode_switch_event_summary = (
        _hybrid_collection_mode_switch_event_summary(data_root)
    )
    hybrid_collection_recovery_policy_event_summary = (
        _hybrid_collection_recovery_policy_event_summary(data_root)
    )
    hybrid_collection_operator_escalation_event_summary = (
        _hybrid_collection_operator_escalation_event_summary(data_root)
    )
    hybrid_collection_operator_escalation_event_trend_summary = (
        _hybrid_collection_operator_escalation_event_trend_summary(data_root)
    )
    hybrid_collection_operator_escalation_event_stability_summary = (
        _hybrid_collection_operator_escalation_event_stability_summary(
            hybrid_collection_operator_escalation_event_trend_summary,
        )
    )
    hybrid_collection_operator_escalation_recovery_event_summary = (
        _hybrid_collection_operator_escalation_recovery_event_summary(data_root)
    )
    hybrid_collection_operator_intervention_event_summary = (
        _hybrid_collection_operator_intervention_event_summary(data_root)
    )
    hybrid_collection_unresolved_escalation_window_summary = (
        _hybrid_collection_unresolved_escalation_window_summary(
            hybrid_collection_operator_escalation_event_summary,
            hybrid_collection_operator_escalation_recovery_event_summary,
        )
    )
    hybrid_collection_recovery_latency_summary = (
        _hybrid_collection_recovery_latency_summary(data_root)
    )
    hybrid_collection_escalation_priority_mix_trend_summary = (
        _hybrid_collection_escalation_priority_mix_trend_summary(data_root)
    )
    hybrid_collection_escalation_resolution_trend_summary = (
        _hybrid_collection_escalation_resolution_trend_summary(
            hybrid_collection_operator_escalation_event_summary,
            hybrid_collection_operator_escalation_recovery_event_summary,
            hybrid_collection_unresolved_escalation_window_summary,
        )
    )
    hybrid_collection_strategy_guidance = _hybrid_collection_strategy_guidance(
        hybrid_collection_runtime_summary,
        hybrid_collection_runtime_history_summary,
    )
    hybrid_collection_recovery_policy = _hybrid_collection_recovery_policy(
        data_root,
        hybrid_collection_runtime_summary,
        hybrid_collection_runtime_history_summary,
        hybrid_collection_strategy_guidance,
        hybrid_collection_mode_switch_event_summary,
        hybrid_collection_recovery_policy_event_summary,
    )
    hybrid_collection_lifecycle_state_summary = (
        _hybrid_collection_lifecycle_state_summary(
            hybrid_collection_runtime_summary,
            hybrid_collection_recovery_policy,
            hybrid_collection_unresolved_escalation_window_summary,
            hybrid_collection_escalation_priority_mix_trend_summary,
        )
    )
    hybrid_collection_action_hint_consistency_summary = (
        _hybrid_collection_action_hint_consistency_summary(
            hybrid_collection_runtime_summary,
            hybrid_collection_lifecycle_state_summary,
        )
    )
    hybrid_collection_operator_intervention_policy_summary = (
        _hybrid_collection_operator_intervention_policy_summary(
            hybrid_collection_lifecycle_state_summary,
            hybrid_collection_action_hint_consistency_summary,
            hybrid_collection_escalation_resolution_trend_summary,
            hybrid_collection_recovery_latency_summary,
        )
    )
    hybrid_collection_operator_intervention_stability_summary = (
        _hybrid_collection_operator_intervention_stability_summary(
            hybrid_collection_operator_intervention_trend_summary,
        )
    )
    hybrid_collection_operator_final_guidance_summary = (
        _hybrid_collection_operator_final_guidance_summary(
            hybrid_collection_operator_intervention_policy_summary,
            hybrid_collection_operator_intervention_stability_summary,
        )
    )
    hybrid_collection_operator_digest_summary = (
        _hybrid_collection_operator_digest_summary(
            hybrid_collection_operator_intervention_policy_summary,
            hybrid_collection_operator_intervention_stability_summary,
            hybrid_collection_operator_final_guidance_summary,
            hybrid_collection_operator_final_guidance_stability_summary,
        )
    )
    hybrid_collection_operator_digest_trend_summary = (
        _hybrid_collection_operator_digest_trend_summary(data_root)
    )
    hybrid_collection_operator_digest_stability_summary = (
        _hybrid_collection_operator_digest_stability_summary(
            hybrid_collection_operator_digest_trend_summary,
        )
    )
    overview_fields: dict[str, Any] = {}
    overview_fields.update(
        _hybrid_collection_operator_overview_fields(hybrid_collection_runtime_summary)
    )
    overview_fields.update(
        _hybrid_collection_operator_history_overview_fields(
            hybrid_collection_runtime_history_summary
        )
    )
    overview_fields.update(
        _hybrid_collection_operator_action_hint_trend_overview_fields(
            hybrid_collection_action_hint_trend_summary
        )
    )
    overview_fields.update(
        _hybrid_collection_operator_final_guidance_trend_overview_fields(
            hybrid_collection_operator_final_guidance_trend_summary
        )
    )
    overview_fields.update(
        _hybrid_collection_operator_final_guidance_stability_overview_fields(
            hybrid_collection_operator_final_guidance_stability_summary
        )
    )
    overview_fields.update(
        _hybrid_collection_operator_digest_trend_overview_fields(
            hybrid_collection_operator_digest_trend_summary
        )
    )
    overview_fields.update(
        _hybrid_collection_operator_digest_stability_overview_fields(
            hybrid_collection_operator_digest_stability_summary
        )
    )
    overview_fields.update(
        _hybrid_collection_operator_intervention_trend_overview_fields(
            hybrid_collection_operator_intervention_trend_summary
        )
    )
    overview_fields.update(
        _hybrid_collection_operator_guidance_overview_fields(
            hybrid_collection_strategy_guidance
        )
    )
    overview_fields.update(
        _hybrid_collection_operator_mode_switch_overview_fields(
            hybrid_collection_mode_switch_event_summary
        )
    )
    overview_fields.update(
        _hybrid_collection_operator_recovery_policy_overview_fields(
            hybrid_collection_recovery_policy
        )
    )
    overview_fields.update(
        _hybrid_collection_operator_recovery_policy_event_overview_fields(
            hybrid_collection_recovery_policy_event_summary
        )
    )
    overview_fields.update(
        _hybrid_collection_operator_escalation_event_overview_fields(
            hybrid_collection_operator_escalation_event_summary
        )
    )
    overview_fields.update(
        _hybrid_collection_operator_escalation_event_trend_overview_fields(
            hybrid_collection_operator_escalation_event_trend_summary
        )
    )
    overview_fields.update(
        _hybrid_collection_operator_escalation_event_stability_overview_fields(
            hybrid_collection_operator_escalation_event_stability_summary
        )
    )
    overview_fields.update(
        _hybrid_collection_operator_escalation_recovery_event_overview_fields(
            hybrid_collection_operator_escalation_recovery_event_summary
        )
    )
    overview_fields.update(
        _hybrid_collection_operator_intervention_event_overview_fields(
            hybrid_collection_operator_intervention_event_summary
        )
    )
    overview_fields.update(
        _hybrid_collection_operator_unresolved_escalation_window_overview_fields(
            hybrid_collection_unresolved_escalation_window_summary
        )
    )
    overview_fields.update(
        _hybrid_collection_operator_lifecycle_state_overview_fields(
            hybrid_collection_lifecycle_state_summary
        )
    )
    overview_fields.update(
        _hybrid_collection_operator_action_hint_consistency_overview_fields(
            hybrid_collection_action_hint_consistency_summary
        )
    )
    overview_fields.update(
        _hybrid_collection_operator_intervention_stability_overview_fields(
            hybrid_collection_operator_intervention_stability_summary
        )
    )
    overview_fields.update(
        _hybrid_collection_operator_intervention_policy_overview_fields(
            hybrid_collection_operator_intervention_policy_summary
        )
    )
    overview_fields.update(
        _hybrid_collection_operator_final_guidance_overview_fields(
            hybrid_collection_operator_final_guidance_summary
        )
    )
    overview_fields.update(
        _hybrid_collection_operator_digest_overview_fields(
            hybrid_collection_operator_digest_summary
        )
    )
    overview_fields.update(
        _hybrid_collection_operator_recovery_latency_overview_fields(
            hybrid_collection_recovery_latency_summary
        )
    )
    overview_fields.update(
        _hybrid_collection_operator_escalation_priority_mix_trend_overview_fields(
            hybrid_collection_escalation_priority_mix_trend_summary
        )
    )
    overview_fields.update(
        _hybrid_collection_operator_escalation_resolution_trend_overview_fields(
            hybrid_collection_escalation_resolution_trend_summary
        )
    )
    summaries = {
        "hybrid_collection_runtime_summary": hybrid_collection_runtime_summary,
        "hybrid_collection_runtime_history_summary": hybrid_collection_runtime_history_summary,
        "hybrid_collection_action_hint_trend_summary": hybrid_collection_action_hint_trend_summary,
        "hybrid_collection_operator_final_guidance_trend_summary": hybrid_collection_operator_final_guidance_trend_summary,
        "hybrid_collection_operator_final_guidance_stability_summary": hybrid_collection_operator_final_guidance_stability_summary,
        "hybrid_collection_operator_digest_trend_summary": hybrid_collection_operator_digest_trend_summary,
        "hybrid_collection_operator_digest_stability_summary": hybrid_collection_operator_digest_stability_summary,
        "hybrid_collection_operator_intervention_trend_summary": hybrid_collection_operator_intervention_trend_summary,
        "hybrid_collection_strategy_guidance": hybrid_collection_strategy_guidance,
        "hybrid_collection_mode_switch_event_summary": hybrid_collection_mode_switch_event_summary,
        "hybrid_collection_recovery_policy": hybrid_collection_recovery_policy,
        "hybrid_collection_recovery_policy_event_summary": hybrid_collection_recovery_policy_event_summary,
        "hybrid_collection_operator_escalation_event_summary": hybrid_collection_operator_escalation_event_summary,
        "hybrid_collection_operator_escalation_event_trend_summary": hybrid_collection_operator_escalation_event_trend_summary,
        "hybrid_collection_operator_escalation_event_stability_summary": hybrid_collection_operator_escalation_event_stability_summary,
        "hybrid_collection_operator_escalation_recovery_event_summary": hybrid_collection_operator_escalation_recovery_event_summary,
        "hybrid_collection_operator_intervention_event_summary": hybrid_collection_operator_intervention_event_summary,
        "hybrid_collection_unresolved_escalation_window_summary": hybrid_collection_unresolved_escalation_window_summary,
        "hybrid_collection_lifecycle_state_summary": hybrid_collection_lifecycle_state_summary,
        "hybrid_collection_action_hint_consistency_summary": hybrid_collection_action_hint_consistency_summary,
        "hybrid_collection_operator_intervention_stability_summary": hybrid_collection_operator_intervention_stability_summary,
        "hybrid_collection_operator_intervention_policy_summary": hybrid_collection_operator_intervention_policy_summary,
        "hybrid_collection_operator_final_guidance_summary": hybrid_collection_operator_final_guidance_summary,
        "hybrid_collection_operator_digest_summary": hybrid_collection_operator_digest_summary,
        "hybrid_collection_recovery_latency_summary": hybrid_collection_recovery_latency_summary,
        "hybrid_collection_escalation_priority_mix_trend_summary": hybrid_collection_escalation_priority_mix_trend_summary,
        "hybrid_collection_escalation_resolution_trend_summary": hybrid_collection_escalation_resolution_trend_summary,
    }
    return summaries, overview_fields

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from src.avm_config import DEFAULT_AVM_CONFIG
from src.status_snapshot_values import _load_json_snapshot
from tools.apply_avm_calibration_patch import (
    apply_avm_calibration_patch,
    apply_command_chain_next_action_policy,
    normalize_calibration_targets_payload,
    resolve_command_chain_artifacts,
    summarize_bundle_command_summary,
    summarize_patch_command_chain,
    summarize_patch_follow_up_command,
    summarize_patch_next_action,
    summarize_patch_next_action_command,
    summarize_patch_risk,
)


def _avm_operator_eval_summary(
    data_root: Path, gate_report_override: dict[str, Any] | None = None
) -> dict[str, Any]:
    avm_dir = data_root / "avm"
    gate_report = (
        gate_report_override
        if isinstance(gate_report_override, dict)
        else _load_json_snapshot(avm_dir / "release_gate.json")
    )
    raw_evaluation = gate_report.get("evaluation")
    evaluation = raw_evaluation if isinstance(raw_evaluation, dict) else {}
    file_calibration_report = normalize_calibration_targets_payload(
        _load_json_snapshot(avm_dir / "calibration_targets.json")
    )
    raw_embedded_calibration_report = (
        evaluation.get("calibration_targets")
        if isinstance(evaluation.get("calibration_targets"), dict)
        else {}
    )

    def _merge_calibration_targets(
        preferred: dict[str, Any], fallback: dict[str, Any]
    ) -> dict[str, Any]:
        merged = dict(fallback)
        for key, value in preferred.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = _merge_calibration_targets(value, merged[key])
            else:
                merged[key] = value
        return merged

    calibration_report = (
        normalize_calibration_targets_payload(
            _merge_calibration_targets(
                raw_embedded_calibration_report, file_calibration_report
            )
        )
        if raw_embedded_calibration_report
        else file_calibration_report
    )
    guidance = (
        calibration_report.get("guidance")
        if isinstance(calibration_report.get("guidance"), dict)
        else {}
    )
    top_calibration_target = calibration_report.get("top_calibration_target")
    if not isinstance(top_calibration_target, dict):
        top_calibration_target = None
    top_calibration_target_hint = calibration_report.get("top_calibration_target_hint")
    if not isinstance(top_calibration_target_hint, dict):
        top_calibration_target_hint = None

    def _serialize_patch_preview(
        preview_payload: dict[str, Any], *, bundle_id: str | None = None
    ) -> dict[str, Any]:
        return {
            "bundle_id": bundle_id,
            "patch_ready": bool(preview_payload.get("changed_key_count") or 0),
            "applied_filter": preview_payload.get("applied_filter"),
            "matched_targets": list(preview_payload.get("matched_targets") or []),
            "changed_key_count": int(preview_payload.get("changed_key_count") or 0),
            "changed_keys": list(preview_payload.get("changed_keys") or []),
            "changed_paths": dict(preview_payload.get("changed_paths") or {}),
            "rollback_patch": dict(preview_payload.get("rollback_patch") or {}),
        }

    calibration_preview_path = avm_dir / "calibration_targets.json"
    config_preview_path = avm_dir / "config.json"

    def _json_file_is_object(path: Path) -> bool:
        from src.runtime_snapshot_cache import snapshots

        return isinstance(snapshots.read(path, invalid=None), dict)

    use_temp_calibration_path = (
        not calibration_preview_path.exists()
        or calibration_report != file_calibration_report
        or not _json_file_is_object(calibration_preview_path)
    )
    use_temp_config_path = config_preview_path.exists() and not _json_file_is_object(
        config_preview_path
    )

    def _build_preview_bundle(
        config_path: Path, calibration_path: Path
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        preview_payload = apply_avm_calibration_patch(
            config_path=config_path,
            calibration_path=calibration_path,
            write_back=False,
        )
        top_preview_payload = apply_avm_calibration_patch(
            config_path=config_path,
            calibration_path=calibration_path,
            write_back=False,
            target_type=str(top_calibration_target.get("target_type") or "")
            if isinstance(top_calibration_target, dict)
            else None,
            target_name=str(top_calibration_target.get("name") or "")
            if isinstance(top_calibration_target, dict)
            else None,
        )
        recommended_bundle = (
            top_calibration_target_hint.get("recommended_bundle")
            if isinstance(top_calibration_target_hint, dict)
            and isinstance(top_calibration_target_hint.get("recommended_bundle"), dict)
            else None
        )
        if recommended_bundle is not None:
            recommended_bundle_preview_payload = apply_avm_calibration_patch(
                config_path=config_path,
                calibration_path=calibration_path,
                write_back=False,
                target_types=list(recommended_bundle.get("target_types") or []),
                target_names=list(recommended_bundle.get("target_names") or []),
            )
        else:
            recommended_bundle_preview_payload = {}
        return preview_payload, top_preview_payload, recommended_bundle_preview_payload

    if use_temp_calibration_path or use_temp_config_path:
        with tempfile.TemporaryDirectory() as tmpdir:
            if use_temp_calibration_path:
                temp_calibration_path = Path(tmpdir) / "calibration_targets.json"
                temp_calibration_path.write_text(
                    json.dumps(calibration_report, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            else:
                temp_calibration_path = calibration_preview_path
            if use_temp_config_path:
                temp_config_path = Path(tmpdir) / "config.json"
                temp_config_path.write_text(
                    json.dumps(DEFAULT_AVM_CONFIG, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            else:
                temp_config_path = config_preview_path
            preview, top_preview, bundle_preview_payload = _build_preview_bundle(
                temp_config_path, temp_calibration_path
            )
    else:
        preview, top_preview, bundle_preview_payload = _build_preview_bundle(
            config_preview_path, calibration_preview_path
        )

    recommended_bundle = (
        top_calibration_target_hint.get("recommended_bundle")
        if isinstance(top_calibration_target_hint, dict)
        and isinstance(top_calibration_target_hint.get("recommended_bundle"), dict)
        else None
    )
    if recommended_bundle is not None:
        recommended_bundle_patch_preview = _serialize_patch_preview(
            bundle_preview_payload,
            bundle_id=str(recommended_bundle.get("bundle_id") or ""),
        )
    else:
        recommended_bundle_patch_preview = _serialize_patch_preview({}, bundle_id=None)

    (
        recommended_bundle_preview_command,
        recommended_bundle_write_command,
        recommended_bundle_verify_command,
        recommended_bundle_gate_command,
    ) = summarize_bundle_command_summary(
        top_calibration_target_hint
        if isinstance(top_calibration_target_hint, dict)
        else None
    )
    recommended_bundle_risk = summarize_patch_risk(recommended_bundle_patch_preview)
    recommended_bundle_next_action = summarize_patch_next_action(
        recommended_bundle_risk, recommended_bundle_patch_preview
    )
    next_action_command = summarize_patch_next_action_command(
        recommended_bundle_next_action,
        preview_command=recommended_bundle_preview_command,
        write_command=recommended_bundle_write_command,
    )
    follow_up_command = summarize_patch_follow_up_command(
        recommended_bundle_next_action,
        preview_command=recommended_bundle_preview_command,
        write_command=recommended_bundle_write_command,
        verify_command=recommended_bundle_verify_command,
    )
    command_chain = summarize_patch_command_chain(
        next_action_command=str(next_action_command.get("next_action_command") or ""),
        next_action_command_kind=str(
            next_action_command.get("next_action_command_kind") or "none"
        ),
        follow_up_command=str(follow_up_command.get("follow_up_command") or ""),
        follow_up_command_kind=str(
            follow_up_command.get("follow_up_command_kind") or "none"
        ),
        verify_command=recommended_bundle_verify_command,
        gate_command=recommended_bundle_gate_command,
    )
    command_chain = resolve_command_chain_artifacts(command_chain, data_root)
    command_chain = apply_command_chain_next_action_policy(
        command_chain,
        next_action=str(
            recommended_bundle_next_action.get("next_action") or "no_action_required"
        ),
    )
    return {
        "calibration_guidance": {
            "status": str(guidance.get("status") or "unavailable"),
            "priority": str(guidance.get("priority") or "info"),
            "recommended_actions": list(guidance.get("recommended_actions") or []),
            "top_reason": str(guidance.get("top_reason") or ""),
        },
        "calibration_target_counts": {
            "global_risk": len(calibration_report.get("global_risk_targets") or []),
            "risk_factor": len(calibration_report.get("risk_factor_targets") or []),
            "temporal": len(calibration_report.get("temporal_targets") or []),
            "strategy": len(calibration_report.get("strategy_targets") or []),
        },
        "top_calibration_target": top_calibration_target,
        "top_calibration_target_hint": top_calibration_target_hint,
        "calibration_patch_preview": _serialize_patch_preview(preview),
        "top_calibration_patch_preview": _serialize_patch_preview(top_preview),
        "recommended_bundle_patch_preview": recommended_bundle_patch_preview,
        "recommended_bundle_preview_command": recommended_bundle_preview_command,
        "recommended_bundle_write_command": recommended_bundle_write_command,
        "recommended_bundle_verify_command": recommended_bundle_verify_command,
        "recommended_bundle_gate_command": recommended_bundle_gate_command,
        "recommended_bundle_risk_level": str(
            recommended_bundle_risk.get("risk_level") or "none"
        ),
        "recommended_bundle_risk_reasons": list(
            recommended_bundle_risk.get("risk_reasons") or []
        ),
        "recommended_bundle_next_action": str(
            recommended_bundle_next_action.get("next_action") or "no_action_required"
        ),
        "recommended_bundle_next_action_reasons": list(
            recommended_bundle_next_action.get("next_action_reasons") or []
        ),
        "recommended_bundle_next_action_command": str(
            next_action_command.get("next_action_command") or ""
        ),
        "recommended_bundle_next_action_command_kind": str(
            next_action_command.get("next_action_command_kind") or "none"
        ),
        "recommended_bundle_follow_up_command": str(
            follow_up_command.get("follow_up_command") or ""
        ),
        "recommended_bundle_follow_up_command_kind": str(
            follow_up_command.get("follow_up_command_kind") or "none"
        ),
        "recommended_bundle_command_chain": command_chain,
        "coordinate_strategy_watchlist": list(
            evaluation.get("coordinate_strategy_watchlist") or []
        ),
        "top_coordinate_strategy_group": evaluation.get(
            "top_coordinate_strategy_group"
        ),
    }

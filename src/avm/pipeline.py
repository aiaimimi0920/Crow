import json
import os
import threading
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

from src.avm_config import DEFAULT_AVM_CONFIG
from src.collection_job_control import JobStopped, job_checkpoint
from tools.apply_avm_calibration_patch import (
    apply_command_chain_next_action_policy,
    apply_avm_calibration_patch,
    normalize_calibration_targets_payload,
    resolve_command_chain_artifacts,
    summarize_bundle_command_summary,
    summarize_patch_command_chain,
    summarize_patch_follow_up_command,
    summarize_patch_next_action,
    summarize_patch_next_action_command,
    summarize_patch_risk,
)


def _bundle_change_summary(bundle_preview: Dict[str, Any]) -> tuple[str, list[str]]:
    changed_keys = list(bundle_preview.get("changed_keys") or [])
    if not changed_keys:
        return "", []
    return str(changed_keys[0]), [str(key) for key in changed_keys[1:]]


def _bundle_command_summary(top_target_hint: Dict[str, Any]) -> tuple[str, str, str, str]:
    return summarize_bundle_command_summary(top_target_hint)


def _json_file_is_object(path: Path) -> bool:
    try:
        if not path.exists():
            return False
        payload = json.loads(path.read_text(encoding="utf-8"))
        return isinstance(payload, dict)
    except Exception:
        return False


@dataclass
class AVMPipelineConfig:
    data_dir: str = "datas"
    alerts_threshold: float = 0.15
    alerts_limit: int = 500


class AVMPipelineManager:
    """Run AVM offline subtasks and expose run/status interfaces."""

    EXPECTED_SUBTASKS = [
        "build_canonical_dataset",
        "build_avm_features",
        "generate_avm_alerts",
        "evaluate_avm",
        "suggest_calibration_targets",
        "generate_release_gate_report",
    ]

    def __init__(self, data_dir: str = "datas") -> None:
        self.data_dir = data_dir
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._state: Dict[str, Any] = {
            "running": False,
            "started_at": None,
            "finished_at": None,
            "current_task": None,
            "tasks": [],
            "error": None,
            "config": None,
            "merge_manifest": {"expected_subtasks": list(self.EXPECTED_SUBTASKS)},
        }

    def _run_task(self, task_name: str, fn) -> None:
        job_checkpoint()
        started = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._state["current_task"] = task_name
            self._state["tasks"].append({"name": task_name, "status": "in_progress", "started_at": started})

        stopped_reason = None
        try:
            result = fn()
            job_checkpoint()
            status = "completed"
            error = None
        except JobStopped as stopped:
            result = None
            status = stopped.reason
            stopped_reason = stopped.reason
            error = None
        except Exception as exc:
            result = None
            status = "failed"
            error = str(exc)

        with self._lock:
            for task in reversed(self._state["tasks"]):
                if task["name"] == task_name and task["status"] == "in_progress":
                    task["status"] = status
                    task["finished_at"] = datetime.now(timezone.utc).isoformat()
                    if isinstance(result, dict):
                        task["result"] = result
                    if error:
                        task["error"] = error
                    break
            if status == "failed":
                self._state["error"] = error
                raise RuntimeError(error)
        if stopped_reason is not None:
            raise JobStopped(stopped_reason)

    def _execute(self, config: AVMPipelineConfig) -> None:
        try:
            from tools.build_canonical_dataset import build_canonical_dataset
            from tools.build_avm_features import build_avm_features
            from tools.generate_avm_alerts import generate_avm_alerts
            from tools.evaluate_avm import BacktestConfig, generate_report
            from tools.suggest_avm_calibration_targets import suggest_calibration_targets
            from tools.avm_release_gate import generate_release_gate_report

            canonical_dir = os.path.join(config.data_dir, "canonical")
            avm_dir = os.path.join(config.data_dir, "avm")
            canonical_path = os.path.join(canonical_dir, "canonical.jsonl")
            feature_path = os.path.join(avm_dir, "features.jsonl")
            feature_stats_path = os.path.join(avm_dir, "feature_stats.json")
            alerts_path = os.path.join(avm_dir, "alerts.json")
            eval_report_path = os.path.join(avm_dir, "eval_report.json")
            calibration_targets_path = os.path.join(avm_dir, "calibration_targets.json")
            gate_report_path = os.path.join(avm_dir, "release_gate.json")

            self._run_task(
                "build_canonical_dataset",
                lambda: build_canonical_dataset(data_dir=config.data_dir, output_dir=canonical_dir),
            )
            self._run_task(
                "build_avm_features",
                lambda: build_avm_features(
                    canonical_path=canonical_path,
                    output_path=feature_path,
                    stats_path=feature_stats_path,
                ),
            )
            self._run_task(
                "generate_avm_alerts",
                lambda: generate_avm_alerts(
                    data_dir=config.data_dir,
                    output_path=alerts_path,
                    threshold=config.alerts_threshold,
                    limit=config.alerts_limit,
                ),
            )
            self._run_task(
                "evaluate_avm",
                lambda: generate_report(
                    BacktestConfig(
                        data_root=Path(config.data_dir),
                        report_path=Path(eval_report_path),
                    )
                ),
            )
            self._run_task(
                "suggest_calibration_targets",
                lambda: _write_calibration_targets(eval_report_path, calibration_targets_path, suggest_calibration_targets),
            )
            self._run_task(
                "generate_release_gate_report",
                lambda: generate_release_gate_report(
                    data_root=Path(config.data_dir),
                    eval_report_path=Path(eval_report_path),
                    gate_report_path=Path(gate_report_path),
                    smoke_sample_size=0,
                    reuse_eval_report=True,
                ),
            )
        finally:
            with self._lock:
                self._state["running"] = False
                self._state["current_task"] = None
                self._state["finished_at"] = datetime.now(timezone.utc).isoformat()

    def _begin_run(self, config: AVMPipelineConfig) -> Dict[str, Any]:
        with self._lock:
            if self._state["running"]:
                snapshot = dict(self._state)
                snapshot["tasks"] = list(self._state.get("tasks", []))
                return {"status": "already_running", "state": snapshot}

            self._state = {
                "running": True,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": None,
                "current_task": None,
                "tasks": [],
                "error": None,
                "config": asdict(config),
                "merge_manifest": {"expected_subtasks": list(self.EXPECTED_SUBTASKS)},
            }
            snapshot = dict(self._state)
            snapshot["tasks"] = list(self._state.get("tasks", []))
            return {"status": "started", "state": snapshot}

    def run(self, async_mode: bool = False, config: Optional[AVMPipelineConfig] = None) -> Dict[str, Any]:
        run_config = config or AVMPipelineConfig(data_dir=self.data_dir)
        init = self._begin_run(run_config)
        if init["status"] == "already_running":
            return init

        if async_mode:
            self._thread = threading.Thread(target=self._execute, args=(run_config,), daemon=True)
            self._thread.start()
            return init

        try:
            self._execute(run_config)
            status = "completed"
        except Exception:
            status = "failed"
        return {"status": status, "state": self.status()}

    # Backward-compatible wrappers
    def start_all_subtasks(self) -> Dict[str, Any]:
        return self.run(async_mode=True)

    def run_all_subtasks_sync(self) -> Dict[str, Any]:
        return self.run(async_mode=False)


    def verify_merge_completeness(self) -> Dict[str, Any]:
        state = self.status()
        expected = list(self.EXPECTED_SUBTASKS)
        observed = [t.get("name") for t in state.get("tasks", [])]
        observed_unique = []
        for name in observed:
            if name not in observed_unique:
                observed_unique.append(name)

        missing = [name for name in expected if name not in observed_unique]
        unexpected = [name for name in observed_unique if name not in expected]
        completed = [t.get("name") for t in state.get("tasks", []) if t.get("status") == "completed"]
        failed = [t.get("name") for t in state.get("tasks", []) if t.get("status") == "failed"]

        return {
            "expected_subtasks": expected,
            "observed_subtasks": observed_unique,
            "missing_subtasks": missing,
            "unexpected_subtasks": unexpected,
            "completed_subtasks": completed,
            "failed_subtasks": failed,
            "is_fully_merged": len(missing) == 0 and len(unexpected) == 0,
        }

    def status(self) -> Dict[str, Any]:
        with self._lock:
            out = dict(self._state)
            out["tasks"] = list(self._state.get("tasks", []))
            # include a lightweight runtime merge completeness check
            expected = list(self.EXPECTED_SUBTASKS)
            observed = []
            for task in out["tasks"]:
                name = task.get("name")
                if name and name not in observed:
                    observed.append(name)
            missing = [name for name in expected if name not in observed]
            unexpected = [name for name in observed if name not in expected]
            out["merge_check"] = {
                "expected_subtasks": expected,
                "observed_subtasks": observed,
                "missing_subtasks": missing,
                "unexpected_subtasks": unexpected,
                "is_fully_merged": len(missing) == 0 and len(unexpected) == 0,
            }
            return out


def _write_calibration_targets(eval_report_path: str, output_path: str, suggest_fn) -> Dict[str, Any]:
    with open(eval_report_path, "r", encoding="utf-8") as fin:
        eval_report = json.load(fin)
    result = normalize_calibration_targets_payload(suggest_fn(eval_report.get("metrics", {}) or {}))
    top_target = result.get("top_calibration_target") if isinstance(result.get("top_calibration_target"), dict) else {}
    top_target_hint = result.get("top_calibration_target_hint") if isinstance(result.get("top_calibration_target_hint"), dict) else {}
    recommended_bundle = top_target_hint.get("recommended_bundle") if isinstance(top_target_hint.get("recommended_bundle"), dict) else {}
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fout:
        json.dump(result, fout, ensure_ascii=False, indent=2)
    if recommended_bundle:
        config_path = Path(output_path).with_name("config.json")
        if config_path.exists() and not _json_file_is_object(config_path):
            with tempfile.TemporaryDirectory() as tmpdir:
                temp_config_path = Path(tmpdir) / "config.json"
                temp_config_path.write_text(json.dumps(DEFAULT_AVM_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
                bundle_preview = apply_avm_calibration_patch(
                    config_path=temp_config_path,
                    calibration_path=Path(output_path),
                    write_back=False,
                    target_types=list(recommended_bundle.get("target_types") or []),
                    target_names=list(recommended_bundle.get("target_names") or []),
                )
        else:
            bundle_preview = apply_avm_calibration_patch(
                config_path=config_path,
                calibration_path=Path(output_path),
                write_back=False,
                target_types=list(recommended_bundle.get("target_types") or []),
                target_names=list(recommended_bundle.get("target_names") or []),
            )
    else:
        bundle_preview = {}
    recommended_bundle_primary_change, recommended_bundle_secondary_changes = _bundle_change_summary(bundle_preview)
    (
        recommended_bundle_preview_command,
        recommended_bundle_write_command,
        recommended_bundle_verify_command,
        recommended_bundle_gate_command,
    ) = _bundle_command_summary(top_target_hint)
    recommended_bundle_risk = summarize_patch_risk(bundle_preview)
    recommended_bundle_next_action = summarize_patch_next_action(recommended_bundle_risk, bundle_preview)
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
        next_action_command_kind=str(next_action_command.get("next_action_command_kind") or "none"),
        follow_up_command=str(follow_up_command.get("follow_up_command") or ""),
        follow_up_command_kind=str(follow_up_command.get("follow_up_command_kind") or "none"),
        verify_command=recommended_bundle_verify_command,
        gate_command=recommended_bundle_gate_command,
    )
    command_chain = resolve_command_chain_artifacts(command_chain, Path(output_path).parent.parent)
    command_chain = apply_command_chain_next_action_policy(
        command_chain,
        next_action=str(recommended_bundle_next_action.get("next_action") or "no_action_required"),
    )
    return {
        **result,
        "output_path": output_path,
        "top_target_name": str(top_target.get("name") or ""),
        "top_target_type": str(top_target.get("target_type") or ""),
        "top_target_hint_status": str(top_target_hint.get("status") or "unknown"),
        "top_target_playbook_id": str(top_target_hint.get("playbook_id") or "unknown"),
        "recommended_bundle_id": str(recommended_bundle.get("bundle_id") or ""),
        "recommended_bundle_changed_key_count": int(bundle_preview.get("changed_key_count") or 0),
        "recommended_bundle_primary_change": recommended_bundle_primary_change,
        "recommended_bundle_secondary_changes": recommended_bundle_secondary_changes,
        "recommended_bundle_preview_command": recommended_bundle_preview_command,
        "recommended_bundle_write_command": recommended_bundle_write_command,
        "recommended_bundle_verify_command": recommended_bundle_verify_command,
        "recommended_bundle_gate_command": recommended_bundle_gate_command,
        "recommended_bundle_risk_level": str(recommended_bundle_risk.get("risk_level") or "none"),
        "recommended_bundle_risk_reasons": list(recommended_bundle_risk.get("risk_reasons") or []),
        "recommended_bundle_next_action": str(recommended_bundle_next_action.get("next_action") or "no_action_required"),
        "recommended_bundle_next_action_reasons": list(recommended_bundle_next_action.get("next_action_reasons") or []),
        "recommended_bundle_next_action_command": str(next_action_command.get("next_action_command") or ""),
        "recommended_bundle_next_action_command_kind": str(next_action_command.get("next_action_command_kind") or "none"),
        "recommended_bundle_follow_up_command": str(follow_up_command.get("follow_up_command") or ""),
        "recommended_bundle_follow_up_command_kind": str(follow_up_command.get("follow_up_command_kind") or "none"),
        "recommended_bundle_command_chain": command_chain,
    }

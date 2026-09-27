"""Fallback state serialization and atomic file replacement."""

from __future__ import annotations

import json
import os

from tools.pc2_solver_config import REPO_ROOT
from tools.pc2_solver_transport import log_event

FALLBACK_STATE_PATH = (
    REPO_ROOT / ".codex-temp" / "bridge-control" / "solver-fallback-state.json"
)


def _default_fallback_state() -> dict[str, object]:
    return {
        "consecutive_failures": 0,
        "window_started_at": None,
        "last_success_at": None,
        "manual_pushed": False,
        "terminal_manual_pending": False,
        "terminal_manual_next_report": 0,
        "auth_complete_pending": False,
        "auth_completion_id": None,
        "auth_complete_attempts": 0,
        "auth_complete_next_retry_at": None,
        "auth_complete_last_error": None,
        "auth_complete_target_url": None,
        "slider_attempts": 0,
        "slider_attempt_started_at": None,
        "slider_last_progress_at": None,
        "slider_next_attempt_at": None,
        "solver_cooldown_until": None,
        "solver_cooldown_reason": None,
        "node_solver_blocked_reported": False,
        "node_solver_blocked_report_attempts": 0,
        "node_solver_blocked_report_next_retry_at": None,
        "node_solver_blocked_report_last_error": None,
        "collection_resume_pending": False,
        "collection_resume_request_id": None,
        "collection_resume_attempts": 0,
        "collection_resume_next_retry_at": None,
        "collection_resume_last_error": None,
        "challenge_id": None,
        "scope": None,
    }


def _load_fallback_state() -> dict[str, object]:
    state = _default_fallback_state()
    try:
        if FALLBACK_STATE_PATH.exists():
            raw = FALLBACK_STATE_PATH.read_text(encoding="utf-8")
            data = json.loads(raw)
            state.update(
                {
                    "consecutive_failures": int(
                        data.get("consecutive_failures", 0) or 0
                    ),
                    "window_started_at": float(data.get("window_started_at") or 0)
                    or None,
                    "last_success_at": float(data.get("last_success_at") or 0) or None,
                    "manual_pushed": bool(data.get("manual_pushed", False)),
                    "terminal_manual_pending": bool(
                        data.get("terminal_manual_pending", False)
                    ),
                    "terminal_manual_next_report": float(
                        data.get("terminal_manual_next_report") or 0
                    ),
                    "auth_complete_pending": bool(
                        data.get("auth_complete_pending", False)
                    ),
                    "auth_completion_id": str(
                        data.get("auth_completion_id") or ""
                    ).strip()
                    or None,
                    "auth_complete_attempts": int(
                        data.get("auth_complete_attempts", 0) or 0
                    ),
                    "auth_complete_next_retry_at": float(
                        data.get("auth_complete_next_retry_at") or 0
                    )
                    or None,
                    "auth_complete_last_error": str(
                        data.get("auth_complete_last_error") or ""
                    ).strip()
                    or None,
                    "auth_complete_target_url": str(
                        data.get("auth_complete_target_url") or ""
                    ).strip()
                    or None,
                    "slider_attempts": int(
                        data.get("slider_attempts", data.get("consecutive_failures", 0))
                        or 0
                    ),
                    "slider_attempt_started_at": float(
                        data.get("slider_attempt_started_at") or 0
                    )
                    or None,
                    "slider_last_progress_at": float(
                        data.get("slider_last_progress_at") or 0
                    )
                    or None,
                    "slider_next_attempt_at": float(
                        data.get("slider_next_attempt_at") or 0
                    )
                    or None,
                    "solver_cooldown_until": float(
                        data.get("solver_cooldown_until") or 0
                    )
                    or None,
                    "solver_cooldown_reason": str(
                        data.get("solver_cooldown_reason") or ""
                    ).strip()
                    or None,
                    "node_solver_blocked_reported": bool(
                        data.get("node_solver_blocked_reported", False)
                    ),
                    "node_solver_blocked_report_attempts": int(
                        data.get("node_solver_blocked_report_attempts", 0) or 0
                    ),
                    "node_solver_blocked_report_next_retry_at": float(
                        data.get("node_solver_blocked_report_next_retry_at") or 0
                    )
                    or None,
                    "node_solver_blocked_report_last_error": str(
                        data.get("node_solver_blocked_report_last_error") or ""
                    ).strip()
                    or None,
                    "collection_resume_pending": bool(
                        data.get("collection_resume_pending", False)
                    ),
                    "collection_resume_request_id": str(
                        data.get("collection_resume_request_id") or ""
                    ).strip()
                    or None,
                    "collection_resume_attempts": int(
                        data.get("collection_resume_attempts", 0) or 0
                    ),
                    "collection_resume_next_retry_at": float(
                        data.get("collection_resume_next_retry_at") or 0
                    )
                    or None,
                    "collection_resume_last_error": str(
                        data.get("collection_resume_last_error") or ""
                    ).strip()
                    or None,
                    "challenge_id": str(data.get("challenge_id") or "").strip() or None,
                    "scope": str(data.get("scope") or "").strip() or None,
                }
            )
            return state
    except Exception:  # noqa: BLE001, S110 -- retain legacy all-or-default recovery without rewriting evidence
        pass
    return state


def _save_fallback_state(state: dict[str, object]) -> None:
    temporary_path = FALLBACK_STATE_PATH.with_name(
        f"{FALLBACK_STATE_PATH.name}.{os.getpid()}.tmp"
    )
    try:
        FALLBACK_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary_path, FALLBACK_STATE_PATH)
    except Exception as exc:  # noqa: BLE001 -- report serialization and filesystem failures without changing callers
        try:
            temporary_path.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001, S110 -- cleanup must not hide the original save failure
            pass
        log_event({"kind": "fallback_state_save_error", "error": repr(exc)})


__all__ = (
    "FALLBACK_STATE_PATH",
    "_default_fallback_state",
    "_load_fallback_state",
    "_save_fallback_state",
)

from __future__ import annotations

from typing import Any


def _normalize_manual_review_maintenance_options(
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    return {
        "window_days": int(payload.get("window_days", 7) or 7),
        "archive_limit": int(payload.get("archive_limit", 200) or 200),
        "sample_limit": int(payload.get("sample_limit", 20) or 20),
        "replay_limit": int(payload.get("replay_limit", 100) or 100),
        "fetch_limit": int(payload.get("fetch_limit", 20) or 20),
        "fetch_timeout": int(payload.get("fetch_timeout", 15) or 15),
        "reconcile_limit": int(payload.get("reconcile_limit", 200) or 200),
        "dry_run": bool(payload.get("dry_run", False)),
        "extract_risk": bool(payload.get("extract_risk", False)),
        "prepare_replay": bool(payload.get("prepare_replay", False)),
        "fetch_archives": bool(payload.get("fetch_archives", False)),
    }


def _validate_manual_review_receipt_payload(
    payload: dict[str, Any],
) -> tuple[bool, dict[str, Any] | None]:
    action = payload.get("action")
    ready_signal = payload.get("ready_signal")
    status = payload.get("status")
    receipt_payload = payload.get("payload")
    mode = str(payload.get("mode", "sync") or "sync").lower()
    if not isinstance(action, str) or not action.strip():
        return False, {
            "code": "AVM_INVALID_RECEIPT_ACTION",
            "message": "action 为必填非空字符串",
            "details": {"required": ["action"]},
        }
    if not isinstance(ready_signal, str) or not ready_signal.strip():
        return False, {
            "code": "AVM_INVALID_RECEIPT_SIGNAL",
            "message": "ready_signal 为必填非空字符串",
            "details": {"required": ["ready_signal"]},
        }
    if not isinstance(status, str) or not status.strip():
        return False, {
            "code": "AVM_INVALID_RECEIPT_STATUS",
            "message": "status 为必填非空字符串",
            "details": {"required": ["status"]},
        }
    if not isinstance(receipt_payload, dict):
        return False, {
            "code": "AVM_INVALID_RECEIPT_PAYLOAD",
            "message": "payload 必须是对象",
            "details": {"required": ["payload"]},
        }
    if mode not in {"sync", "async"}:
        return False, {
            "code": "AVM_INVALID_RECEIPT_MODE",
            "message": "mode 只能是 sync 或 async",
            "details": {"allowed": ["sync", "async"]},
        }
    return True, None


def _validate_manual_review_receipt_delete_payload(
    payload: dict[str, Any],
) -> tuple[bool, dict[str, Any] | None]:
    action = payload.get("action")
    ready_signal = payload.get("ready_signal")
    if not isinstance(action, str) or not action.strip():
        return False, {
            "code": "AVM_INVALID_RECEIPT_ACTION",
            "message": "action 为必填非空字符串",
            "details": {"required": ["action"]},
        }
    if not isinstance(ready_signal, str) or not ready_signal.strip():
        return False, {
            "code": "AVM_INVALID_RECEIPT_SIGNAL",
            "message": "ready_signal 为必填非空字符串",
            "details": {"required": ["ready_signal"]},
        }
    return True, None

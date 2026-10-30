"""Allowlisted evidence from existing solver logs; never retain raw payloads."""

import hashlib
import json
import re
from datetime import datetime

from tools.solver_binding_evidence import binding_evidence as _target_binding_evidence
from tools.solver_pointer_evidence import (
    POINTER_PHASES,
)
from tools.solver_pointer_evidence import (
    pointer_evidence as _pointer_evidence,
)

KINDS = {
    "local_solver_start",
    "local_solver_end",
    "local_solver_diagnostic",
    "auth_completion_challenge_resolved",
    "auth_complete_result",
    "auth_complete_retry_pending",
    "auth_complete_confirmed",
    "solver_cooldown_started",
    "solver_cooldown_elapsed",
}
PHASES = {
    "target_binding",
    "slider_geometry",
    "drag_distance",
    "pointer_failure",
    "pointer_hit",
    "input_receipt",
    "input_receipt_unavailable",
    "cursor_position",
    "os_drag",
    "drag_complete",
    "verification",
    "verified",
    "challenge_failure",
    "slider_missing",
    "nc_retry_click",
    "nc_retry_restored",
    "nc_retry_authenticated",
    "nc_retry_uncertain",
}
FAILURES = {
    "cdp_unavailable",
    "deadline_exceeded",
    "challenge_retry_exhausted",
    "max_attempts_exceeded",
    "challenge_loading",
    "manual_required",
    "cancelled",
    "slider_not_found",
    "slider_endpoint_unconfirmed",
    "timeout",
    "execution_unavailable",
}
PROFILES = {
    "fast_exact_v3",
    "legacy_exact_release",
    "dense_exact_release",
    "slow_exact_v4",
    "slow_settle_v4",
    "slow_dense_v4",
}


def fingerprint(value):
    return hashlib.sha256(str(value).encode()).hexdigest() if value else None


def timestamp(value):
    # Docker emits nanoseconds; the supported Python runtime accepts microseconds.
    value = re.sub(r"(\.\d{6})\d+", r"\1", value).replace("Z", "+00:00")
    return datetime.fromisoformat(value).timestamp()


def _challenge_failure_evidence(event):
    evidence = {}
    if "code" in event:
        code = event["code"]
        evidence["code"] = (
            code
            if isinstance(code, str)
            and re.fullmatch(r"error:[0-9]{1,6}|none|other", code)
            else "other"
        )
    if type(event.get("retryable")) is bool:
        evidence["retryable"] = event["retryable"]
    for key, allowed, fallback in (
        ("code_kind", {"absent", "numeric", "opaque", "invalid"}, "invalid"),
        ("ready_state", {"loading", "interactive", "complete", "unknown"}, "unknown"),
    ):
        if key in event:
            value = event[key]
            evidence[key] = (
                value if isinstance(value, str) and value in allowed else fallback
            )
    for key in ("target_ready", "probe_failed"):
        if type(event.get(key)) is bool:
            evidence[key] = event[key]
    return evidence


def project_line(line, container_id):
    try:
        at, raw = line.split(" ", 1)
        epoch = timestamp(at)
        event = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if (
        not isinstance(event, dict)
        or not isinstance(event.get("kind"), str)
        or event["kind"] not in KINDS
    ):
        return None
    kind = event["kind"]
    if kind == "local_solver_diagnostic" and (
        not isinstance(event.get("phase"), str) or event["phase"] not in PHASES
    ):
        return None
    out = {
        "id": fingerprint(container_id + line),
        "container_id": container_id,
        "at": at,
        "epoch": epoch,
        "kind": kind,
    }
    if kind == "local_solver_start":
        from urllib.parse import urlsplit

        try:
            host = urlsplit(str(event.get("target_url") or "")).hostname
        except ValueError:
            host = None
        out["scope"] = {"sf-item.taobao.com": "detail", "sf.taobao.com": "seed"}.get(
            host, "unknown"
        )
        out["target_hash"] = fingerprint(event.get("target_url"))
    if kind == "local_solver_end":
        out["success"] = event.get("success") is True
        reason = event.get("failure_reason")
        out["failure_reason"] = (
            reason
            if isinstance(reason, str) and reason in FAILURES
            else ("other" if reason else None)
        )
    if kind == "local_solver_diagnostic":
        out["phase"] = event["phase"]
        if event["phase"] in POINTER_PHASES:
            out.update(_pointer_evidence(event))
        if event["phase"] == "nc_retry_click":
            index, count = event.get("candidate_index"), event.get("candidate_count")
            if type(index) is int and type(count) is int and 1 <= index <= count <= 16:
                out.update(candidate_index=index, candidate_count=count)
            candidate = event.get("candidate_kind")
            out["candidate_kind"] = (
                candidate
                if isinstance(candidate, str)
                and candidate
                in {
                    "widget_centerline",
                    "widget_vertical",
                    "retry_text",
                    "widget_fallback",
                }
                else "unknown"
            )
        if event["phase"] == "challenge_failure":
            out.update(_challenge_failure_evidence(event))
        if event["phase"] == "target_binding":
            out.update(_target_binding_evidence(event))
        if event["phase"] == "slider_missing":
            ready = event.get("ready_state")
            out["ready_state"] = (
                ready
                if isinstance(ready, str)
                and ready in {"loading", "interactive", "complete"}
                else "unknown"
            )
            for key in (
                "probe_failed",
                "target_ready",
                "challenge_present",
                "login_required",
                "hard_block",
                "explicit_failure",
                "authenticated_page",
            ):
                if type(event.get(key)) is bool:
                    out[key] = event[key]
        if event["phase"] == "os_drag":
            out["automatic_input"] = event.get("input") == "pyautogui"
            out["profile"] = (
                event.get("profile")
                if isinstance(event.get("profile"), str)
                and event["profile"] in PROFILES
                else "other"
            )
        if event["phase"] not in {"input_receipt", "input_receipt_unavailable"}:
            for key in ("distance", "screen_x", "screen_y"):
                value = event.get(key)
                if type(value) in (int, float) and -100000 < value < 100000:
                    out[key] = value
        for key in (
            "success",
            "slider_gone",
            "challenge_gone",
            "has_error",
            "error_text",
            "error_widget",
        ):
            if type(event.get(key)) is bool:
                out[key] = event[key]
    if kind == "auth_completion_challenge_resolved":
        out["challenge_hash"] = fingerprint(event.get("completion_challenge_id"))
    if kind == "solver_cooldown_started":
        for key in ("until", "seconds", "cycles", "consecutive_failures"):
            value = event.get(key)
            if type(value) in (int, float) and 0 <= value < 1e12:
                out[key] = value
    if kind.startswith("auth_complete"):
        result = event.get("result") or {}
        if not isinstance(result, dict):
            return None
        confirmed = kind == "auth_complete_confirmed" or result.get("confirmed") is True
        payload = result.get("result", {}) if kind == "auth_complete_result" else result
        if not isinstance(payload, dict):
            return None
        state = result.get("state") or {}
        state = state if isinstance(state, dict) else {}
        request = event.get("request") if kind == "auth_complete_result" else None
        request = request if isinstance(request, dict) else {}
        response_id = payload.get("completion_id")
        request_id = request.get("completion_id")
        out["completion_hash"] = fingerprint(response_id or request_id)
        binding = request or state
        if (request_id and response_id and request_id != response_id) or (
            request.get("scope")
            and payload.get("scope")
            and request["scope"] != payload["scope"]
        ):
            binding = {}
        out["challenge_hash"] = fingerprint(binding.get("challenge_id"))
        out["target_hash"] = fingerprint(
            binding.get("target_url") or binding.get("auth_complete_target_url")
        )
        out["confirmed"] = confirmed and payload.get("auth_state_confirmed") is True
        out["automatic_source"] = payload.get("source") == "pc2_local_solver"
        scope = payload.get("scope") or request.get("scope")
        out["scope"] = scope if scope in ("seed", "detail") else "unknown"
        snapshot = payload.get("cookie_snapshot") or {}
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        detail = snapshot.get("result") or {}
        detail = detail if isinstance(detail, dict) else {}
        status = snapshot.get("status")
        out["snapshot_status"] = (
            status
            if isinstance(status, str)
            and status
            in {"pending", "running", "busy", "completed", "failed", "skipped"}
            else "unknown"
        )
        reason = detail.get("reason") or snapshot.get("reason")
        out["snapshot_reason"] = (
            reason
            if isinstance(reason, str)
            and reason
            in {
                "cookie_snapshot_candidate_unhealthy",
                "refresh_already_running",
                "snapshot_worker_start_failed",
                "disabled_by_request",
            }
            else ("other" if reason else None)
        )
        health = detail.get("health") or {}
        health = health if isinstance(health, dict) else {}
        out["snapshot_refreshed"] = (
            snapshot.get("refreshed") is True or detail.get("refreshed") is True
        )
        out["bound_health_verified"] = (
            health.get("scope") == out["scope"] and health.get("scope_healthy") is True
        ) or (out["scope"] == "seed" and health.get("healthy") is True)
    return out


def summarize(events):
    """Keep local outcomes, correlated auth proof and observation gaps distinct."""
    attempts, current, pending = [], None, {}
    unlinked_auth = set()
    automatic_auth = set()
    for event in events:
        kind = event["kind"]
        if kind == "local_solver_start":
            current = {
                "id": event["id"],
                "container_id": event["container_id"],
                "started_at": event["at"],
                "scope": event["scope"],
                "target_hash": event.get("target_hash"),
                "drags": [],
                "verified": False,
                "completed": False,
                "local_success": False,
                "automatic_local_success": False,
                "auth_confirmed": False,
                "bound_health_verified": False,
            }
            attempts.append(current)
        elif kind == "observer_restart_boundary":
            current = None
        elif current and event["container_id"] == current["container_id"]:
            if kind == "local_solver_diagnostic" and not current["completed"]:
                if event["phase"] == "os_drag":
                    current["drags"].append(
                        {
                            k: event[k]
                            for k in (
                                "at",
                                "automatic_input",
                                "profile",
                                "distance",
                                "screen_x",
                                "screen_y",
                            )
                            if k in event
                        }
                    )
                if event["phase"] == "verified":
                    current["verified"] = True
                if event["phase"] in POINTER_PHASES:
                    evidence = current.setdefault("pointer_events", [])
                    if len(evidence) < 64:
                        evidence.append(
                            {
                                k: event[k]
                                for k in (
                                    "at",
                                    "phase",
                                    "reason",
                                    "check",
                                    "delta",
                                    "corrections",
                                    "distance",
                                    "track_width",
                                    "slider_width",
                                    "backend_completed",
                                    "press_seen",
                                    "press_on_target",
                                    "pressed_moves",
                                    "release_seen",
                                    "document_current",
                                )
                                if k in event
                            }
                        )
                if event["phase"] == "challenge_failure":
                    current["last_challenge_failure"] = {
                        "at": event["at"],
                        **_challenge_failure_evidence(event),
                    }
                if event["phase"] == "target_binding":
                    bindings = current.setdefault("target_binding_events", [])
                    if len(bindings) < 64:
                        bindings.append(
                            {"at": event["at"], **_target_binding_evidence(event)}
                        )
                if event["phase"] in {
                    "nc_retry_click",
                    "nc_retry_restored",
                    "nc_retry_authenticated",
                    "nc_retry_uncertain",
                }:
                    retries = current.setdefault("nc_retry_events", [])
                    if len(retries) < 64:
                        retries.append(
                            {
                                k: event[k]
                                for k in (
                                    "at",
                                    "phase",
                                    "candidate_index",
                                    "candidate_count",
                                    "candidate_kind",
                                )
                                if k in event
                            }
                        )
            elif kind == "local_solver_end" and not current["completed"]:
                current.update(
                    completed=True,
                    ended_at=event["at"],
                    local_success=event["success"],
                    failure_reason=event["failure_reason"],
                )
                current["automatic_local_success"] = bool(
                    event["success"]
                    and current["verified"]
                    and any(d["automatic_input"] for d in current["drags"])
                )
            elif (
                kind == "auth_completion_challenge_resolved"
                and current["completed"]
                and current["local_success"]
            ):
                current["challenge_hash"] = event.get("challenge_hash")
        if kind == "auth_complete_result":
            key = event.get("completion_hash")
            candidates = [
                a
                for a in attempts
                if a["completed"]
                and a["local_success"]
                and event.get("challenge_hash")
                and event.get("target_hash")
                and a.get("challenge_hash") == event["challenge_hash"]
                and a.get("target_hash") == event["target_hash"]
                and a["container_id"] == event["container_id"]
                and a["scope"] == event["scope"]
            ]
            if key and key not in pending and len(candidates) == 1:
                pending[key] = candidates[0]
        if kind.startswith("auth_complete"):
            key = event.get("completion_hash")
            linked = pending.get(key)
            matching = bool(
                linked
                and linked["scope"] == event["scope"]
                and linked["container_id"] == event["container_id"]
            )
            if not event.get("confirmed"):
                if (
                    matching
                    and not linked["auth_confirmed"]
                    and (
                        kind == "auth_complete_result" or event.get("automatic_source")
                    )
                ):
                    for field in ("snapshot_status", "snapshot_reason"):
                        if field in event:
                            linked["last_pending_" + field] = event[field]
                continue
            if event.get("automatic_source"):
                automatic_auth.add(key or event["id"])
            if matching and event.get("automatic_source"):
                if not linked["auth_confirmed"]:
                    linked["auth_confirmed_at"] = event["at"]
                    elapsed = event["epoch"] - timestamp(linked["ended_at"])
                    if elapsed >= 0:
                        linked["auth_confirmation_seconds"] = round(elapsed, 3)
                linked["auth_confirmed"] = True
                linked["bound_health_verified"] |= event.get(
                    "bound_health_verified", False
                )
                unlinked_auth.discard(key)
            else:
                unlinked_auth.add(key or event["id"])
    counts = {
        key: sum(bool(a[key]) for a in attempts)
        for key in (
            "completed",
            "local_success",
            "automatic_local_success",
            "auth_confirmed",
            "bound_health_verified",
        )
    }
    counts.update(
        started=len(attempts),
        automatic_auth_confirmations=len(automatic_auth),
        incomplete=sum(not a["completed"] for a in attempts),
        unlinked_auth_confirmations=len(unlinked_auth),
        auth_confirmed_without_verified_drag=sum(
            a["auth_confirmed"] and not a["automatic_local_success"] for a in attempts
        ),
        local_success_without_auth_confirmation=sum(
            a["automatic_local_success"] and not a["auth_confirmed"] for a in attempts
        ),
    )
    return {"counts": counts, "attempts": attempts}

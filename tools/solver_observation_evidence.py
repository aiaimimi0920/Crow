"""Allowlisted evidence from existing solver logs; never retain raw payloads."""

import hashlib
import json
import re
from datetime import datetime

KINDS = {
    "local_solver_start",
    "local_solver_end",
    "local_solver_diagnostic",
    "auth_completion_challenge_resolved",
    "auth_complete_result",
    "auth_complete_confirmed",
    "solver_cooldown_started",
    "solver_cooldown_elapsed",
}
PHASES = {"os_drag", "drag_complete", "verification", "verified", "challenge_failure"}
FAILURES = {
    "challenge_retry_exhausted",
    "max_attempts_exceeded",
    "challenge_loading",
    "manual_required",
    "cancelled",
    "slider_not_found",
    "timeout",
}
PROFILES = {"fast_exact_v3", "legacy_exact_release", "dense_exact_release"}


def fingerprint(value):
    return hashlib.sha256(str(value).encode()).hexdigest() if value else None


def timestamp(value):
    # Docker emits nanoseconds; the supported Python runtime accepts microseconds.
    value = re.sub(r"(\.\d{6})\d+", r"\1", value).replace("Z", "+00:00")
    return datetime.fromisoformat(value).timestamp()


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
        if event["phase"] == "os_drag":
            out["automatic_input"] = event.get("input") == "pyautogui"
            out["profile"] = (
                event.get("profile")
                if isinstance(event.get("profile"), str)
                and event["profile"] in PROFILES
                else "other"
            )
        for key in ("distance", "screen_x", "screen_y"):
            value = event.get(key)
            if type(value) in (int, float) and -100000 < value < 100000:
                out[key] = value
        for key in ("success", "slider_gone", "challenge_gone", "has_error"):
            if type(event.get(key)) is bool:
                out[key] = event[key]
    if kind == "auth_completion_challenge_resolved":
        out["challenge_hash"] = fingerprint(event.get("completion_challenge_id"))
    if kind.startswith("auth_complete"):
        result = event.get("result") or {}
        if not isinstance(result, dict):
            return None
        confirmed = kind == "auth_complete_confirmed" or result.get("confirmed") is True
        payload = result.get("result", {}) if kind == "auth_complete_result" else result
        if not isinstance(payload, dict):
            return None
        out["completion_hash"] = fingerprint(payload.get("completion_id"))
        state = result.get("state") or {}
        state = state if isinstance(state, dict) else {}
        out["challenge_hash"] = fingerprint(state.get("challenge_id"))
        out["target_hash"] = fingerprint(state.get("auth_complete_target_url"))
        out["confirmed"] = confirmed and payload.get("auth_state_confirmed") is True
        out["automatic_source"] = payload.get("source") == "pc2_local_solver"
        out["scope"] = (
            payload.get("scope")
            if payload.get("scope") in ("seed", "detail")
            else "unknown"
        )
        snapshot = payload.get("cookie_snapshot") or {}
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        detail = snapshot.get("result") or {}
        detail = detail if isinstance(detail, dict) else {}
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
                and current["automatic_local_success"]
            ):
                current["challenge_hash"] = event.get("challenge_hash")
        if kind == "auth_complete_result":
            key = event.get("completion_hash")
            candidates = [
                a
                for a in attempts
                if a["automatic_local_success"]
                and event.get("challenge_hash")
                and event.get("target_hash")
                and a.get("challenge_hash") == event["challenge_hash"]
                and a.get("target_hash") == event["target_hash"]
                and a["container_id"] == event["container_id"]
                and a["scope"] == event["scope"]
            ]
            if key and key not in pending and len(candidates) == 1:
                pending[key] = candidates[0]
        if kind.startswith("auth_complete") and event.get("confirmed"):
            key = event.get("completion_hash")
            linked = pending.get(key)
            if event.get("automatic_source"):
                automatic_auth.add(key or event["id"])
            if (
                linked
                and event.get("automatic_source")
                and linked["scope"] == event["scope"]
            ):
                linked["auth_confirmed"] = True
                linked["auth_confirmed_at"] = event["at"]
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
    )
    return {"counts": counts, "attempts": attempts}

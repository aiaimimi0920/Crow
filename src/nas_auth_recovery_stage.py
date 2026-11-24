"""Stage-bound recovery receipts; cookie transport alone is never seed proof."""

import copy
import time
import uuid


class StageRecoveryMixin:
    def request_manual(self, request_id: str, *, scope: str = "", challenge_id: str = "",
                       target_url: str = "", now: float | None = None) -> dict[str, object]:
        """Explicit human completion starts a recovery without waiting for a stall."""
        current = time.time() if now is None else float(now)
        if not self.enabled:
            return {"ok": False, "error": "auth recovery is disabled"}
        if scope and scope not in {"seed", "detail"}:
            return {"ok": False, "error": "invalid scope"}
        try:
            if uuid.UUID(request_id).hex != request_id:
                raise ValueError("Noncanonical request ID")
        except (ValueError, TypeError, AttributeError):
            return {"ok": False, "error": "request_id must be a UUID hex string"}
        with self._locked_state():
            self._expire_active_locked(current)
            last = self._state.get("last_result")
            if isinstance(last, dict) and last.get("manual_request_id") == request_id:
                if (last.get("scope") or "") != scope:
                    return {"ok": False, "error": "request scope changed"}
                self._persist_locked()
                return {"ok": True, "idempotent": True, "result": copy.deepcopy(last)}
            active = self._state.get("active")
            if (isinstance(active, dict) and not active.get("manual_request_id")
                    and active.get("status") in {"requested", "pc1_claimed"}):
                # A fresh ID invalidates any in-flight automatic PC1 publication.
                # Manual snapshots have their own immutable path, so an old
                # watcher cannot overwrite the session being handed to PC2.
                self._finish_locked(status="failed", reason="desktop_manual_takeover", now=current)
                active = None
            if isinstance(active, dict) and active.get("manual_request_id") != request_id:
                if scope:
                    return {"ok": False, "busy": True, "error": "another recovery is active"}
                self._persist_locked()
                return {"ok": True, "existing_recovery": True, "recovery": self._safe_active(active)}
            if not isinstance(active, dict):
                active = {
                    "recovery_id": f"auth-recovery-{request_id}", "status": "requested",
                    "baseline_captured_count": self._state.get("last_captured_count"),
                    "requested_at_epoch": current, "updated_at_epoch": current,
                    "trigger_reason": "desktop_manual_completion",
                    "scope": scope or None, "challenge_id": challenge_id, "target_url": target_url,
                }
                self._state["active"] = active
            active.setdefault("manual_request_id", request_id)
            if scope and any(active.get(key) != value for key, value in
                             (("scope", scope), ("challenge_id", challenge_id), ("target_url", target_url))):
                return {"ok": False, "error": "request identity changed"}
            self._persist_locked()
            return {"ok": True, "recovery": self._safe_active(active)}

    def register_stage_auth_pc2(self, *, now=None):
        with self._locked_state():
            current = time.time() if now is None else now
            if current - float(self._state.get("pc2_stage_auth_seen_at") or 0) >= 30:
                self._state["pc2_stage_auth_seen_at"] = current
                self._persist_locked()

    def _stage_retry_ready_locked(
        self,
        *,
        signal: str,
        normalized_count: int | None,
        stage_context: dict[str, str] | None,
    ) -> bool:
        last_result = self._state.get("last_result")
        if not isinstance(last_result, dict) or last_result.get("status") != "succeeded":
            return False
        if signal == "detail_challenge_stalled" and normalized_count is not None:
            try:
                completed_count = int(last_result.get("captured_count"))
            except (TypeError, ValueError):
                completed_count = normalized_count
            return normalized_count > completed_count
        if signal == "seed_challenge_stalled" and isinstance(stage_context, dict):
            last_challenge = str(last_result.get("challenge_id") or "").strip()
            next_challenge = str(stage_context.get("challenge_id") or "").strip()
            return bool(
                last_result.get("scope") == "seed"
                and stage_context.get("scope") == "seed"
                and last_challenge
                and next_challenge
                and next_challenge != last_challenge
            )
        return False

    def _bind_stage_context_locked(
        self,
        active: dict[str, object],
        *,
        stalled_scope: str | None,
        scoped_stall: bool,
        stage_context: dict[str, str] | None,
        now: float,
    ) -> None:
        if not (
            scoped_stall
            and stalled_scope in {"seed", "detail"}
            and 0 <= now - float(self._state.get("pc2_stage_auth_seen_at") or 0) < 120
            and isinstance(stage_context, dict)
            and stage_context.get("scope") == stalled_scope
            and str(stage_context.get("challenge_id") or "").strip()
            and str(stage_context.get("target_url") or "").strip()
        ):
            return
        active.update(
            scope=stalled_scope,
            challenge_id=str(stage_context["challenge_id"]).strip(),
            target_url=str(stage_context["target_url"]).strip(),
        )

    def accept_stage_result(self, payload, *, validate_and_clear, captured_count, now=None):
        current = time.time() if now is None else now
        with self._locked_state():
            self._expire_active_locked(current)
            active = self._state.get("active")
            recovery_id = payload.get("recovery_id")
            if not isinstance(active, dict) or active.get("recovery_id") != recovery_id:
                last = self._state.get("last_result") or {}
                if (last.get("recovery_id") == recovery_id and last.get("scope") == payload.get("scope")
                        and payload.get("node_id") == "pc2" and payload.get("protocol_version") == 2
                        and payload.get("snapshot_sha256") == last.get("snapshot_sha256")
                        and payload.get("target_url") == last.get("target_url")):
                    return {"ok": True, "idempotent": True, "status": last.get("status")}
                return {"ok": False, "stale_recovery": True}
            scope = active.get("scope")
            if (scope not in {"seed", "detail"} or payload.get("scope") != scope
                    or payload.get("node_id") != "pc2" or payload.get("protocol_version") != 2
                    or payload.get("snapshot_sha256") != (active.get("snapshot") or {}).get("sha256")):
                return {"ok": False, "error": "stage receipt mismatch"}
            if active.get("status") not in {"restarting", "verifying"}:
                return {"ok": False, "error": "stage receipt not expected"}
            if payload.get("success") is not True:
                reason = "stage_probe_unavailable" if payload.get("reason") == "stage_probe_unavailable" else "stage_probe_failed"
                self._finish_locked(status="failed", reason=reason, now=current)
                self._persist_locked()
                return {"ok": True, "status": "failed"}
            if scope == "seed" and (payload.get("probe_authenticated") is not True
                                    or payload.get("target_url") != active.get("target_url")):
                return {"ok": False, "error": "seed access proof required"}
            if active.get("status") == "verifying":
                return {"ok": True, "status": "verifying", "idempotent": True}
            error = validate_and_clear(dict(active))
            if error:
                self._finish_locked(status="failed", reason=error, now=current)
                self._persist_locked()
                return {"ok": True, "status": "failed"}
            if scope == "seed":
                self._finish_locked(status="succeeded", reason="seed_payload_verified", now=current)
                result = {"ok": True, "status": "succeeded"}
            else:
                # Only captures after import/clear count as detail recovery evidence.
                self._state["last_captured_count"] = captured_count
                active.update(status="verifying", updated_at_epoch=current,
                              verify_deadline_epoch=current + self.verify_timeout_seconds)
                result = {"ok": True, "status": "verifying"}
            self._persist_locked()
            return result

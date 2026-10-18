from __future__ import annotations

import contextlib
import copy
import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .auth_recovery_codes import (
    ACTIVE_STATUSES as ACTIVE_STATUSES,  # noqa: PLC0414 -- public re-export
)
from .auth_recovery_codes import TIMEOUT_REASONS
from .nas_auth_recovery_stage import StageRecoveryMixin

SUCCESSFUL_RECOVERY_NEW_PROGRESS_RETRY_SIGNALS = {"detail_challenge_stalled"}
SCOPED_CHALLENGE_STALL_SIGNALS = {
    "seed_challenge_stalled": "seed",
    "detail_challenge_stalled": "detail",
}


class NasAuthRecoveryCoordinator(StageRecoveryMixin):
    """Durable single-flight coordination for PC1 -> NAS -> PC2 auth recovery."""

    def __init__(
        self,
        state_path: str | Path,
        *,
        enabled: bool = True,
        stall_seconds: float = 1800,
        pc1_timeout_seconds: float = 1800,
        pc2_timeout_seconds: float = 600,
        verify_timeout_seconds: float = 600,
        cooldown_seconds: float = 1800,
        automatic_auth_allowed=None,
    ) -> None:
        self.state_path = Path(state_path)
        self.enabled = bool(enabled)
        self.stall_seconds = max(float(stall_seconds), 1.0)
        self.pc1_timeout_seconds = max(float(pc1_timeout_seconds), 1.0)
        self.pc2_timeout_seconds = max(float(pc2_timeout_seconds), 1.0)
        self.verify_timeout_seconds = max(float(verify_timeout_seconds), 1.0)
        self.cooldown_seconds = max(float(cooldown_seconds), 0.0)
        self._automatic_auth_allowed = automatic_auth_allowed
        self._lock = threading.RLock()
        self._state = self._load_state()

    @staticmethod
    def _default_state() -> dict[str, Any]:
        return {
            "schema_version": 1,
            "last_captured_count": None,
            "last_progress_at_epoch": None,
            "last_sample_at_epoch": None,
            "pending_detail_count": 0,
            "cooldown_until_epoch": None,
            "active": None,
            "last_result": None,
            "pc2_stage_auth_seen_at": None,
        }

    def _load_state(self) -> dict[str, Any]:
        state = self._default_state()
        try:
            loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return state
        if not isinstance(loaded, dict):
            return state
        for key in state:
            if key in loaded:
                state[key] = loaded[key]
        active = state.get("active")
        if not isinstance(active, dict) or active.get("status") not in ACTIVE_STATUSES:
            state["active"] = None
        if not isinstance(state.get("last_result"), dict):
            state["last_result"] = None
        return state

    def _persist_locked(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_name(
            f"{self.state_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        )
        try:
            temporary.write_text(
                json.dumps(self._state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temporary, self.state_path)
        finally:
            temporary.unlink(missing_ok=True)

    @contextlib.contextmanager
    def _locked_state(self):
        """Reload under an OS file lock so multiple API processes cannot fork state."""
        with self._lock:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            lock_path = self.state_path.with_name(f"{self.state_path.name}.lock")
            with lock_path.open("a+b") as lock_file:
                if os.name == "nt":
                    import msvcrt

                    lock_file.seek(0, os.SEEK_END)
                    if lock_file.tell() == 0:
                        lock_file.write(b"\0")
                        lock_file.flush()
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
                    unlock = lambda: msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                    unlock = lambda: fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                try:
                    self._state = self._load_state()
                    yield
                finally:
                    lock_file.seek(0)
                    unlock()

    @staticmethod
    def _safe_active(active: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(active, dict):
            return None
        snapshot = active.get("snapshot")
        safe_snapshot = None
        if isinstance(snapshot, dict):
            safe_snapshot = {
                "sha256": str(snapshot.get("sha256") or ""),
                "cookie_count": int(snapshot.get("cookie_count") or 0),
                "created_at_epoch": snapshot.get("created_at_epoch"),
            }
        return {
            "recovery_id": active.get("recovery_id"),
            "status": active.get("status"),
            "baseline_captured_count": active.get("baseline_captured_count"),
            "requested_at_epoch": active.get("requested_at_epoch"),
            "updated_at_epoch": active.get("updated_at_epoch"),
            "pc1_claimed_at_epoch": active.get("pc1_claimed_at_epoch"),
            "pc2_claimed_at_epoch": active.get("pc2_claimed_at_epoch"),
            "restart_requested_at_epoch": active.get("restart_requested_at_epoch"),
            "verify_deadline_epoch": active.get("verify_deadline_epoch"),
            "trigger_reason": active.get("trigger_reason"),
            "manual_request_id": active.get("manual_request_id"),
            "scope": active.get("scope"),
            "challenge_id": active.get("challenge_id"),
            "target_url": active.get("target_url"),
            "snapshot": safe_snapshot,
        }

    def _automatic_allowed_locked(self, now: float) -> bool:
        try:
            allowed = self._automatic_auth_allowed is None or self._automatic_auth_allowed() is True
        except Exception:  # noqa: BLE001 -- failed liveness checks must deny automatic prompts
            allowed = False
        active = self._state.get("active")
        if not allowed and isinstance(active, dict) and not active.get("manual_request_id"):
            self._finish_locked(status="failed", reason="collectors_unavailable", now=now)
            self._persist_locked()
        return allowed

    def snapshot(self, *, now: float | None = None) -> dict[str, Any]:
        current = time.time() if now is None else float(now)
        with self._locked_state():
            allowed = self._automatic_allowed_locked(current)
            state = copy.deepcopy(self._state)
        last_progress = state.get("last_progress_at_epoch")
        stalled_for = (
            max(0.0, current - float(last_progress))
            if last_progress is not None
            else 0.0
        )
        return {
            "enabled": self.enabled,
            "automatic_auth_allowed": allowed,
            "stage_auth_protocol": 2,
            "pc2_stage_auth_ready": 0 <= current - float(state.get("pc2_stage_auth_seen_at") or 0) < 120,
            "stall_seconds": self.stall_seconds,
            "stalled_for_seconds": stalled_for,
            "last_captured_count": state.get("last_captured_count"),
            "last_progress_at_epoch": last_progress,
            "last_sample_at_epoch": state.get("last_sample_at_epoch"),
            "pending_detail_count": int(state.get("pending_detail_count") or 0),
            "cooldown_until_epoch": state.get("cooldown_until_epoch"),
            "active": self._safe_active(state.get("active")),
            "last_result": copy.deepcopy(state.get("last_result")),
        }

    def _finish_locked(
        self,
        *,
        status: str,
        reason: str,
        now: float,
        captured_count: int | None = None,
    ) -> None:
        active = self._state.get("active")
        if not isinstance(active, dict):
            return
        self._state["last_result"] = {
            "recovery_id": active.get("recovery_id"),
            "status": status,
            "reason": str(reason or ""),
            "baseline_captured_count": active.get("baseline_captured_count"),
            "captured_count": captured_count,
            "trigger_reason": active.get("trigger_reason"),
            "manual_request_id": active.get("manual_request_id"),
            "scope": active.get("scope"),
            "challenge_id": active.get("challenge_id"),
            "target_url": active.get("target_url"),
            "snapshot_sha256": (active.get("snapshot") or {}).get("sha256"),
            "finished_at_epoch": now,
        }
        self._state["active"] = None
        self._state["cooldown_until_epoch"] = (
            now + self.cooldown_seconds if self.cooldown_seconds > 0 else None
        )

    def _expire_active_locked(self, now: float) -> None:
        active = self._state.get("active")
        if not isinstance(active, dict):
            return
        status = str(active.get("status") or "")
        requested_at = float(active.get("requested_at_epoch") or now)
        updated_at = float(active.get("updated_at_epoch") or requested_at)
        if status in {"requested", "pc1_claimed"}:
            deadline = requested_at + self.pc1_timeout_seconds
        elif status == "verifying":
            deadline = float(active.get("verify_deadline_epoch") or 0)
        else:
            deadline = updated_at + self.pc2_timeout_seconds
        if deadline > 0 and now >= deadline:
            self._finish_locked(
                status="failed",
                reason=TIMEOUT_REASONS[status],
                now=now,
                captured_count=self._state.get("last_captured_count"),
            )

    def sample(
        self,
        captured_count: int | None,
        pending_detail_count: int,
        *,
        operator_paused: bool = False,
        recovery_signal: str | None = None,
        recovery_signal_stall_seconds: float | None = None,
        blocked_scopes: tuple[str, ...] = (),
        now: float | None = None,
    ) -> dict[str, Any]:
        current = time.time() if now is None else float(now)
        pending = max(int(pending_detail_count or 0), 0)
        normalized_count = None if captured_count is None else max(int(captured_count), 0)
        with self._locked_state():
            previous = self._state.get("last_captured_count")
            automatic_allowed = self._automatic_allowed_locked(current)
            self._state["last_sample_at_epoch"] = current
            self._state["pending_detail_count"] = pending

            if normalized_count is not None:
                if previous is None or normalized_count < int(previous):
                    self._state["last_captured_count"] = normalized_count
                    self._state["last_progress_at_epoch"] = current
                elif normalized_count > int(previous):
                    self._state["last_captured_count"] = normalized_count
                    self._state["last_progress_at_epoch"] = current
                    active = self._state.get("active")
                    if (
                        isinstance(active, dict)
                        and active.get("scope") != "seed"
                        and (
                            active.get("scope") not in blocked_scopes
                            if active.get("scope")
                            else not blocked_scopes
                        )
                        and not (active.get("scope") and operator_paused)
                        and (not active.get("manual_request_id") or active.get("status") == "verifying")
                    ):
                        self._finish_locked(
                            status="succeeded",
                            reason="captured_count_advanced",
                            now=current,
                            captured_count=normalized_count,
                        )
                elif self._state.get("last_progress_at_epoch") is None:
                    self._state["last_progress_at_epoch"] = current

            self._expire_active_locked(current)
            active = self._state.get("active")
            last_progress = self._state.get("last_progress_at_epoch")
            cooldown_until = float(self._state.get("cooldown_until_epoch") or 0)
            stalled_for = (
                current - float(last_progress) if last_progress is not None else 0.0
            )
            normalized_signal = str(recovery_signal or "").strip()
            signal_stall_seconds = max(
                float(
                    self.stall_seconds
                    if recovery_signal_stall_seconds is None
                    else recovery_signal_stall_seconds
                ),
                1.0,
            )
            stalled_scope = SCOPED_CHALLENGE_STALL_SIGNALS.get(normalized_signal)
            scoped_stall = bool(stalled_scope and stalled_scope in blocked_scopes)
            # Scoped signals have already passed their own challenge-age threshold.
            signal_triggered = bool(
                normalized_signal and (scoped_stall or stalled_for >= signal_stall_seconds)
            )
            last_result = self._state.get("last_result")
            successful_signal_retry_ready = False
            if (
                signal_triggered
                and normalized_signal in SUCCESSFUL_RECOVERY_NEW_PROGRESS_RETRY_SIGNALS
                and normalized_count is not None
                and isinstance(last_result, dict)
                and last_result.get("status") == "succeeded"
            ):
                try:
                    completed_count = int(last_result.get("captured_count"))
                except (TypeError, ValueError):
                    completed_count = normalized_count
                successful_signal_retry_ready = normalized_count > completed_count
            may_trigger = bool(
                self.enabled
                and automatic_allowed
                and normalized_count is not None
                and (pending > 0 or (scoped_stall and stalled_scope == "seed"))
                and not operator_paused
                and not isinstance(active, dict)
                and (
                    current >= cooldown_until
                    or successful_signal_retry_ready
                )
                and last_progress is not None
                and (stalled_for >= self.stall_seconds or signal_triggered)
            )
            if may_trigger:
                self._state["active"] = {
                    "recovery_id": f"auth-recovery-{uuid.uuid4().hex}",
                    "status": "requested",
                    "baseline_captured_count": normalized_count,
                    "requested_at_epoch": current,
                    "updated_at_epoch": current,
                    "trigger_reason": (
                        normalized_signal
                        if signal_triggered
                        else "captured_count_stalled"
                    ),
                }
            self._persist_locked()
        return self.snapshot(now=current)

    def claim(
        self,
        role: str,
        recovery_id: str,
        node_id: str,
        *,
        now: float | None = None,
    ) -> dict[str, Any]:
        current = time.time() if now is None else float(now)
        if not self.enabled:
            return {"ok": False, "error": "auth recovery is disabled"}
        normalized_role = str(role or "").strip().lower()
        expected_status = "requested" if normalized_role == "pc1" else "snapshot_ready"
        claimed_status = "pc1_claimed" if normalized_role == "pc1" else "pc2_claimed"
        if normalized_role not in {"pc1", "pc2"}:
            return {"ok": False, "error": "role must be pc1 or pc2"}
        if str(node_id or "").strip().lower() != normalized_role:
            return {"ok": False, "error": "node_id does not match role"}
        with self._locked_state():
            self._automatic_allowed_locked(current)
            self._expire_active_locked(current)
            active = self._state.get("active")
            if not isinstance(active, dict):
                return {"ok": False, "error": "no active recovery"}
            if str(active.get("recovery_id") or "") != str(recovery_id or ""):
                return {"ok": False, "stale_recovery": True, "error": "recovery_id does not match"}
            status = str(active.get("status") or "")
            claimant_key = f"{normalized_role}_node_id"
            if status == claimed_status and str(active.get(claimant_key) or "") == str(node_id or ""):
                return {"ok": True, "idempotent": True, "recovery": self._safe_active(active)}
            if status != expected_status:
                return {"ok": False, "error": f"recovery is {status}, expected {expected_status}"}
            active["status"] = claimed_status
            active[claimant_key] = str(node_id or normalized_role)
            active[f"{normalized_role}_claimed_at_epoch"] = current
            active["updated_at_epoch"] = current
            self._persist_locked()
            return {"ok": True, "idempotent": False, "recovery": self._safe_active(active)}

    def snapshot_ready(
        self,
        recovery_id: str,
        *,
        sha256: str,
        cookie_count: int,
        created_at_epoch: float | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        current = time.time() if now is None else float(now)
        if not self.enabled:
            return {"ok": False, "error": "auth recovery is disabled"}
        digest = str(sha256 or "").strip().lower()
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            return {"ok": False, "error": "sha256 must be a 64-character hexadecimal digest"}
        normalized_count = max(int(cookie_count or 0), 0)
        if normalized_count <= 0:
            return {"ok": False, "error": "cookie_count must be positive"}
        with self._locked_state():
            active = self._state.get("active")
            if not isinstance(active, dict):
                return {"ok": False, "error": "no active recovery"}
            if str(active.get("recovery_id") or "") != str(recovery_id or ""):
                return {"ok": False, "stale_recovery": True, "error": "recovery_id does not match"}
            if (
                active.get("status") == "snapshot_ready"
                and (active.get("snapshot") or {}).get("sha256") == digest
                and int((active.get("snapshot") or {}).get("cookie_count") or 0) == normalized_count
            ):
                return {"ok": True, "idempotent": True, "recovery": self._safe_active(active)}
            if active.get("status") != "pc1_claimed":
                return {"ok": False, "error": f"recovery is {active.get('status')}, expected pc1_claimed"}
            active["snapshot"] = {
                "sha256": digest,
                "cookie_count": normalized_count,
                "created_at_epoch": float(created_at_epoch or current),
            }
            active["status"] = "snapshot_ready"
            active["updated_at_epoch"] = current
            self._persist_locked()
            return {"ok": True, "idempotent": False, "recovery": self._safe_active(active)}

    def pc2_restarting(
        self,
        recovery_id: str,
        *,
        now: float | None = None,
    ) -> dict[str, Any]:
        current = time.time() if now is None else float(now)
        if not self.enabled:
            return {"ok": False, "error": "auth recovery is disabled"}
        with self._locked_state():
            active = self._state.get("active")
            if not isinstance(active, dict):
                return {"ok": False, "error": "no active recovery"}
            if str(active.get("recovery_id") or "") != str(recovery_id or ""):
                return {"ok": False, "stale_recovery": True, "error": "recovery_id does not match"}
            if active.get("status") == "restarting":
                return {"ok": True, "idempotent": True, "recovery": self._safe_active(active)}
            if active.get("status") != "pc2_claimed":
                return {"ok": False, "error": f"recovery is {active.get('status')}, expected pc2_claimed"}
            active["status"] = "restarting"
            active["restart_requested_at_epoch"] = current
            active["updated_at_epoch"] = current
            self._persist_locked()
            return {"ok": True, "idempotent": False, "recovery": self._safe_active(active)}

    def result(
        self,
        recovery_id: str,
        *,
        success: bool,
        reason: str = "",
        now: float | None = None,
    ) -> dict[str, Any]:
        current = time.time() if now is None else float(now)
        if not self.enabled:
            return {"ok": False, "error": "auth recovery is disabled"}
        with self._locked_state():
            active = self._state.get("active")
            if not isinstance(active, dict):
                last = self._state.get("last_result")
                if isinstance(last, dict) and str(last.get("recovery_id") or "") == str(recovery_id or ""):
                    return {"ok": True, "idempotent": True, "status": last.get("status")}
                return {"ok": False, "error": "no active recovery"}
            if str(active.get("recovery_id") or "") != str(recovery_id or ""):
                return {"ok": False, "stale_recovery": True, "error": "recovery_id does not match"}
            if active.get("status") not in {"restarting", "verifying"}:
                return {"ok": False, "error": f"recovery is {active.get('status')}, expected restarting"}
            if not success:
                self._finish_locked(
                    status="failed",
                    reason=str(reason or "pc2_recovery_failed"),
                    now=current,
                    captured_count=self._state.get("last_captured_count"),
                )
                self._persist_locked()
                return {"ok": True, "status": "failed"}
            active["status"] = "verifying"
            active["updated_at_epoch"] = current
            active["verify_deadline_epoch"] = current + self.verify_timeout_seconds
            self._persist_locked()
            return {
                "ok": True,
                "status": "verifying",
                "recovery": self._safe_active(active),
            }

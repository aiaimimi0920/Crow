"""Scoped challenge receipts and pause decisions for an injected runtime."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from src.archive_json_io import write_json
from src.collection_control_state import CHALLENGE_SCOPES, new_scope_state
from src.project_environment import getenv as project_getenv
from src.solver_request_payload import _normalize_challenge_scope

if TYPE_CHECKING:
    from src.runtime_state import RuntimeState


def _number(state: Mapping[str, object], key: str) -> float:
    return float(cast("str | float", state.get(key) or 0))


def _request(state: Mapping[str, object]) -> dict[str, object]:
    return dict(cast("Mapping[str, object]", state.get("last_request") or {}))


def find_challenge_scope(
    challenge_id: str | None,
    status: Callable[[str], Mapping[str, object]],
) -> str | None:
    normalized = str(challenge_id or "").strip()
    if not normalized:
        return None
    for scope in CHALLENGE_SCOPES:
        if str(status(scope).get("challenge_id") or "").strip() == normalized:
            return scope
    return None


@dataclass(frozen=True)
class SolverScopeRuntime:
    runtime: RuntimeState
    data_dir: Path
    legacy_state_path: Callable[[], Path]
    force_reset_seconds: float

    def state_root_path(self) -> Path:
        configured = str(project_getenv("CROW_SOLVER_STATE_DIR") or "").strip()
        if configured:
            state_dir = configured
        else:
            # Scoped receipts share the legacy receipt's configured root.
            try:
                state_dir = str(Path(self.legacy_state_path()).parent)
            except Exception:
                state_dir = str(self.data_dir)
        state_dir = state_dir.strip() or str(self.data_dir)
        try:
            root = Path(state_dir).expanduser().resolve()
        except OSError:
            root = Path(state_dir).expanduser()
        self.runtime.control.bind_root(str(root))
        return root

    def state_path(self, scope: str) -> Path:
        normalized = _normalize_challenge_scope(scope) or "unknown"
        return self.state_root_path() / f"solver-challenge-state-{normalized}.json"

    def read(self, scope: str) -> dict[str, object]:
        with self.runtime.lock:
            return self._read_locked(scope)

    def _read_locked(self, scope: str) -> dict[str, object]:
        normalized = _normalize_challenge_scope(scope)
        if not normalized:
            return new_scope_state()
        path = self.state_path(normalized)
        state = self.runtime.control.scope_snapshot(normalized)
        if state.get("challenge_id") and not path.exists():
            # A latch from another root must not outlive its durable receipt.
            return new_scope_state()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return state
        if not isinstance(payload, dict) or payload.get("active") is not True:
            cleared = new_scope_state()
            self.runtime.control.set_scope(normalized, cleared)
            return cleared
        state.update(
            {
                "challenge_id": str(payload.get("challenge_id") or "").strip() or None,
                "last_request": dict(payload.get("last_request") or {})
                if isinstance(payload.get("last_request"), dict)
                else {},
                "first_seen_epoch": float(
                    payload.get("first_seen_epoch")
                    or payload.get("created_at_epoch")
                    or 0
                ),
                "pause_started_epoch": float(
                    payload.get("pause_started_epoch")
                    or payload.get("created_at_epoch")
                    or 0
                ),
                "paused": bool(payload.get("paused", True)),
                "pause_reason": str(
                    payload.get("pause_reason") or "captcha_solver"
                ).strip()
                or "captcha_solver",
                "manual_required": bool(payload.get("manual_required", False)),
                "manual_only": bool(payload.get("manual_only", False)),
                "last_status": str(payload.get("last_status") or "running"),
                "last_failure_reason": str(
                    payload.get("last_failure_reason") or ""
                ).strip()
                or None,
                "node_solver_blocked": bool(payload.get("node_solver_blocked", False)),
                "node_solver_blocked_at_epoch": float(
                    payload.get("node_solver_blocked_at_epoch") or 0
                ),
                "node_solver_blocked_reason": str(
                    payload.get("node_solver_blocked_reason") or ""
                ).strip()
                or None,
                "node_solver_blocked_attempts": int(
                    payload.get("node_solver_blocked_attempts") or 0
                ),
            }
        )
        return state

    def persist(self, scope: str, state: Mapping[str, object]) -> str | None:
        # Readers must observe the file publication and cache update together.
        with self.runtime.lock:
            return self._persist_locked(scope, state)

    def _persist_locked(self, scope: str, state: Mapping[str, object]) -> str | None:
        normalized = _normalize_challenge_scope(scope)
        if not normalized:
            return None
        path = self.state_path(normalized)
        payload = {
            "active": bool(state.get("challenge_id")),
            "scope": normalized,
            "challenge_id": state.get("challenge_id"),
            "first_seen_epoch": _number(state, "first_seen_epoch"),
            "pause_started_epoch": _number(state, "pause_started_epoch"),
            "updated_at_epoch": time.time(),
            "paused": bool(state.get("paused")),
            "pause_reason": state.get("pause_reason"),
            "manual_required": bool(state.get("manual_required")),
            "manual_only": bool(state.get("manual_only")),
            "last_status": state.get("last_status"),
            "last_failure_reason": state.get("last_failure_reason"),
            "node_solver_blocked": bool(state.get("node_solver_blocked")),
            "node_solver_blocked_at_epoch": _number(
                state, "node_solver_blocked_at_epoch"
            ),
            "node_solver_blocked_reason": state.get("node_solver_blocked_reason"),
            "node_solver_blocked_attempts": int(
                cast("str | int", state.get("node_solver_blocked_attempts") or 0)
            ),
            "last_request": _request(state),
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            write_json(path, payload, indent=2)
            self.runtime.control.set_scope(normalized, state)
        except Exception as error:
            return repr(error)
        return None

    def age(self, scope: str, now: float | None = None) -> float:
        state = self.read(scope)
        first_seen = _number(state, "first_seen_epoch")
        if first_seen <= 0 or not state.get("challenge_id"):
            return 0.0
        return max(0.0, (time.time() if now is None else float(now)) - first_seen)

    def manual_flag_path(self, scope: str | None = None) -> str:
        state_dir = str(
            project_getenv("CROW_SOLVER_STATE_DIR") or self.data_dir
        ).strip() or str(self.data_dir)
        if scope is None:
            return os.path.join(state_dir, "force_unlock.flag")
        normalized = _normalize_challenge_scope(scope)
        return str(Path(state_dir) / f"force_unlock-{normalized}.flag")

    def manual_flag_exists(self) -> bool:
        try:
            return os.path.exists(self.manual_flag_path())
        except Exception:
            return False

    def transient_pause_active(self) -> bool:
        with self.runtime.lock:
            control = self.runtime.control.snapshot()
            execution = self.runtime.solver.snapshot()
        return bool(
            control.paused
            and control.reason == "captcha_solver"
            and execution.running
            and execution.last_status == "running"
            and execution.failure_reason != "manual_required"
        )

    def effectively_paused(self) -> bool:
        if self.manual_flag_exists():
            return True
        if not self.runtime.control.snapshot().paused:
            return False
        return not self.transient_pause_active()

    def scope_effectively_paused(
        self, scope: str, *, check_manual_flag: bool = True
    ) -> bool:
        if check_manual_flag and self.manual_flag_exists():
            return True
        normalized = _normalize_challenge_scope(scope)
        if normalized not in CHALLENGE_SCOPES:
            return self.effectively_paused()
        scoped = self.status(normalized)
        if scoped.get("paused") or scoped.get("manual_required"):
            return True
        control = self.runtime.control.snapshot()
        # Operator pauses apply to both collectors; solver pauses stay scoped.
        if control.paused and control.reason in (None, "operator"):
            return True
        if control.reason == "manual_required" and not any(
            self.status(candidate).get("paused") for candidate in CHALLENGE_SCOPES
        ):
            return True
        return False

    def set_pause(
        self, paused: bool, reason: str | None = None, *, scope: str | None = None
    ) -> None:
        normalized = _normalize_challenge_scope(scope)
        with self.runtime.lock:
            if not normalized:
                self.runtime.control.set_pause(paused, reason)
                return
            self.state_root_path()
            state = self.runtime.control.scope_snapshot(normalized)
            state["paused"] = bool(paused)
            state["pause_reason"] = (
                str(reason or "").strip() or None if paused else None
            )
            if paused and not state.get("pause_started_epoch"):
                state["pause_started_epoch"] = time.time()
            if not paused:
                state["force_reset_required"] = False
            self.persist(normalized, state)
            current = self.runtime.control.snapshot()
            if paused:
                active_reason = (
                    current.reason
                    if current.reason in {"operator", "manual_required"}
                    else reason or "captcha_solver"
                )
                self.runtime.control.set_pause(True, active_reason)
            elif not any(
                bool(self.read(candidate).get("paused"))
                for candidate in CHALLENGE_SCOPES
            ) and current.reason in {"captcha_solver", "manual_required"}:
                self.runtime.control.set_pause(False)

    def status(self, scope: str, now: float | None = None) -> dict[str, object]:
        normalized = _normalize_challenge_scope(scope) or "seed"
        current_time = time.time() if now is None else float(now)
        state = self.read(normalized)
        challenge_id = str(state.get("challenge_id") or "").strip() or None
        first_seen = _number(state, "first_seen_epoch")
        age = (
            max(0.0, current_time - first_seen)
            if challenge_id and first_seen > 0
            else 0.0
        )
        force_reset_required = bool(
            challenge_id and state.get("paused") and age >= self.force_reset_seconds
        )
        terminal_blocked = bool(
            state.get("paused") and state.get("node_solver_blocked")
        )
        # Older terminal receipts omitted the explicit manual-only flag.
        return {
            "scope": normalized,
            "challenge_id": challenge_id,
            "first_seen_epoch": first_seen or None,
            "pause_started_epoch": _number(state, "pause_started_epoch") or None,
            "challenge_age_seconds": age,
            "paused": bool(state.get("paused")),
            "pause_reason": "manual_required"
            if terminal_blocked
            else state.get("pause_reason"),
            "manual_required": bool(state.get("manual_required") or terminal_blocked),
            "manual_only": bool(state.get("manual_only") or terminal_blocked),
            "force_reset_required": force_reset_required,
            "last_status": "manual_required"
            if terminal_blocked
            else state.get("last_status") or "idle",
            "last_failure_reason": state.get("last_failure_reason"),
            "node_solver_blocked": bool(state.get("node_solver_blocked")),
            "node_solver_blocked_at_epoch": _number(
                state, "node_solver_blocked_at_epoch"
            )
            or None,
            "node_solver_blocked_reason": state.get("node_solver_blocked_reason"),
            "node_solver_blocked_attempts": int(
                cast("str | int", state.get("node_solver_blocked_attempts") or 0)
            ),
            "last_request": _request(state),
        }

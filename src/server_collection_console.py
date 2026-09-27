"""Native ownership of operator/node authentication completion."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from .auth_cleanup_journal import AuthCleanupIntent
from .auth_cleanup_recovery import legacy_cleanup_state, restore_auth_cleanup
from .auth_completion_contracts import CookieFinalizer, CookieScheduler
from .collection_control_state import CHALLENGE_SCOPES
from .runtime_state import RuntimeState
from .solver_captcha_reports import PayloadFlag
from .solver_pause_cleanup import PauseSetter


@dataclass(frozen=True)
class AuthCompletion:
    runtime: Callable[[], RuntimeState]
    normalize_completion: Callable[[object], str | None]
    normalize_scope: Callable[[object], str | None]
    scope_for_id: Callable[[object], str | None]
    scope_status: Callable[[str | None], dict[str, object]]
    status: Callable[[], dict[str, object]]
    node_matches: Callable[[dict[str, object], str], bool]
    was_confirmed: Callable[[str | None], bool]
    infer_scope: Callable[[object], str | None]
    confirmed: Callable[[dict[str, object], str | None], bool]
    flag: PayloadFlag
    manual_only: Callable[[object], bool]
    cookie_status: Callable[[], dict[str, object]]
    read_scope: Callable[[str | None], dict[str, object]]
    flag_manual_only: Callable[[], bool]
    state_root: Callable[[], Path]
    clear_pause: Callable[[str | None], str | None]
    remember_confirmation: Callable[[str | None], str | None]
    remember_completion: Callable[[object], None]
    persist_scope: Callable[[str, Mapping[str, object]], str | None]
    persist_legacy: Callable[[str, dict[str, str]], str | None]
    write_manual_flag: Callable[[float], str | None]
    set_pause: PauseSetter
    schedule: CookieScheduler
    finalize: CookieFinalizer
    scope_flag_path: Callable[[str | None], str]
    runtime_label: Callable[[], str]
    matches_target: Callable[[str, object, dict[str, object]], bool]

    __all__: ClassVar[list[str]] = ["_collection_observer_auth_complete_payload"]

    def _collection_observer_auth_complete_payload(
        self,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:

        payload = payload if isinstance(payload, dict) else {}
        completion_id = self.normalize_completion(payload.get("completion_id"))
        source = str(payload.get("source") or "operator")
        # Bind validation and the snapshot job to one observed challenge generation.
        with self.runtime().lock:
            completion_scope = self.normalize_scope(
                payload.get("scope")
            ) or self.scope_for_id(payload.get("challenge_id"))
            if source == "seed_auth_probe":
                status = self.scope_status("seed")
                if not self.matches_target("seed", payload.get("target_url"), status):
                    return {
                        "ok": False,
                        "auth_state_confirmed": False,
                        "stale_challenge": True,
                        "error": "seed probe target does not match the blocked collection page",
                    }
            if source == "pc2_local_solver" and not completion_id:
                solver_status = self.status()
                return {
                    "ok": False,
                    "action": "auth_complete",
                    "source": source,
                    "completion_id": None,
                    "auth_state_confirmed": False,
                    "challenge_id": self.runtime().recovery.snapshot().challenge_id,
                    "paused": bool(solver_status.get("paused")),
                    "captcha_solver": solver_status,
                    "error": "completion_id is required for pc2_local_solver",
                }
            if not self.node_matches(payload, source):
                solver_status = self.status()
                return {
                    "ok": False,
                    "action": "auth_complete",
                    "source": source,
                    "completion_id": completion_id,
                    "auth_state_confirmed": False,
                    "stale_challenge": True,
                    "challenge_id": self.runtime().recovery.snapshot().challenge_id,
                    "paused": bool(solver_status.get("paused")),
                    "captcha_solver": solver_status,
                    "error": "completion belongs to an older captcha challenge",
                }
            previously_confirmed = self.was_confirmed(completion_id)
            before_status = self.status()
            completion_request = before_status.get("last_request")
            if not isinstance(completion_request, dict) or not completion_request:
                completion_request = self.runtime().recovery.snapshot().last_request
            if completion_scope not in CHALLENGE_SCOPES:
                completion_scope = self.infer_scope(completion_request)
            if completion_scope in CHALLENGE_SCOPES:
                scoped_request = self.scope_status(completion_scope).get("last_request")
                if isinstance(scoped_request, dict) and scoped_request:
                    completion_request = scoped_request
            reported_completion_id = str(payload.get("challenge_id") or "").strip()
            if (
                completion_scope in CHALLENGE_SCOPES
                and not self.scope_status(completion_scope).get("challenge_id")
                and reported_completion_id
                == str(self.runtime().recovery.snapshot().challenge_id or "").strip()
            ):
                completion_scope = None
            already_clear = self.confirmed(before_status, completion_scope)
            refresh_cookie_snapshot = self.flag(
                payload, "refresh_cookie_snapshot", True
            )
            snapshot_gate_required = bool(
                refresh_cookie_snapshot
                or source == "pc2_local_solver"
                or self.manual_only(completion_request)
            )
            snapshot_payload = dict(payload)
            if snapshot_gate_required:
                snapshot_payload["refresh_cookie_snapshot"] = True
            expected_challenge_id = (
                str(
                    self.scope_status(completion_scope).get("challenge_id") or ""
                ).strip()
                or None
                if completion_scope in CHALLENGE_SCOPES
                else str(self.runtime().recovery.snapshot().challenge_id or "").strip()
                or None
            )

        clear_error: str | None = None
        receipt_error: str | None = None
        finalization_error: str | None = None
        recovery_error: str | None = None
        if previously_confirmed:
            auth_state_confirmed = already_clear
            cookie_snapshot = self.cookie_status()
        elif not snapshot_gate_required or already_clear:
            # Keep validation, cleanup and outcome atomic with challenge publication.
            # Scheduling/finalization stays outside this lock to preserve lock order.
            with self.runtime().lock:
                current_challenge_id = (
                    str(
                        self.scope_status(completion_scope).get("challenge_id") or ""
                    ).strip()
                    or None
                    if completion_scope in CHALLENGE_SCOPES
                    else str(
                        self.runtime().recovery.snapshot().challenge_id or ""
                    ).strip()
                    or None
                )
                if (
                    current_challenge_id != expected_challenge_id
                    or not self.node_matches(payload, source)
                ):
                    return {
                        "ok": False,
                        "action": "auth_complete",
                        "auth_state_confirmed": False,
                        "stale_challenge": True,
                        "challenge_id": current_challenge_id,
                        "error": "completion belongs to an older captcha challenge",
                    }
                recovery_before_cleanup = self.runtime().recovery.snapshot()
                cleanup_before = (
                    self.read_scope(completion_scope)
                    if completion_scope in CHALLENGE_SCOPES
                    else legacy_cleanup_state(
                        recovery_before_cleanup,
                        manual_only=self.flag_manual_only(),
                    )
                )
                intent = AuthCleanupIntent(
                    self.state_root(),
                    completion_scope or None,
                    cleanup_before,
                    completion_id,
                )
                clear_error = intent.prepare(read_scope=self.read_scope)
                if clear_error is None:
                    with intent.preserve_during_cleanup():
                        clear_error = self.clear_pause(completion_scope or None)
                cleared_status = self.status()
                auth_state_confirmed = clear_error is None and self.confirmed(
                    cleared_status, completion_scope
                )
                if auth_state_confirmed:
                    receipt_error = self.remember_confirmation(completion_id)
                    if receipt_error is None:
                        receipt_error = intent.finish()
                    auth_state_confirmed = receipt_error is None
                if auth_state_confirmed:
                    self.runtime().solver.record_outcome("manual_auth_completed")
                    self.remember_completion(completion_request)
                else:
                    if receipt_error and (
                        cleanup_before.get("challenge_id")
                        or recovery_before_cleanup.challenge_id
                    ):
                        recovery_error = restore_auth_cleanup(
                            completion_scope,
                            cleanup_before,
                            recovery_before_cleanup,
                            runtime=self.runtime(),
                            persist_scope=self.persist_scope,
                            persist_legacy=self.persist_legacy,
                            write_manual_flag=self.write_manual_flag,
                        )
                    self.runtime().solver.record_outcome(
                        "manual_required", "manual_required"
                    )
                    self.set_pause(
                        True, "manual_required", scope=completion_scope or None
                    )
            cookie_snapshot = self.schedule(snapshot_payload, completion_id)
        else:
            # Phase one: the operator/node reported a completed browser challenge,
            # but HTTP workers must remain paused until those cookies pass the same
            # health probe used by collection.  The background retry performs phase
            # two and clears this exact challenge only after a healthy snapshot.
            auth_state_confirmed = False
            with self.runtime().lock:
                current_challenge_id = (
                    str(
                        self.scope_status(completion_scope).get("challenge_id") or ""
                    ).strip()
                    or None
                    if completion_scope in CHALLENGE_SCOPES
                    else str(
                        self.runtime().recovery.snapshot().challenge_id or ""
                    ).strip()
                    or None
                )
                if current_challenge_id != expected_challenge_id:
                    return {
                        "ok": False,
                        "action": "auth_complete",
                        "auth_state_confirmed": False,
                        "stale_challenge": True,
                        "challenge_id": current_challenge_id,
                        "error": "completion belongs to an older captcha challenge",
                    }
                self.runtime().solver.record_outcome(
                    "manual_required", "manual_required"
                )
                self.set_pause(True, "manual_required", scope=completion_scope or None)
            cookie_snapshot = self.schedule(
                snapshot_payload,
                completion_id,
                finalize_auth=True,
                expected_challenge_id=expected_challenge_id,
                completion_request=(
                    dict(completion_request)
                    if isinstance(completion_request, dict)
                    else None
                ),
            )
            if (
                cookie_snapshot.get("status") == "completed"
                and cookie_snapshot.get("refreshed") is True
            ):
                finalization = self.finalize(
                    completion_id,
                    expected_challenge_id=expected_challenge_id,
                    completion_request=(
                        dict(completion_request)
                        if isinstance(completion_request, dict)
                        else None
                    ),
                )
                auth_state_confirmed = finalization.get("auth_state_confirmed") is True
                finalization_error = (
                    str(finalization.get("error") or "").strip() or None
                )
                cookie_snapshot = {
                    **cookie_snapshot,
                    "auth_state_confirmed": auth_state_confirmed,
                    "auth_finalization": finalization,
                }

        # Receipt replay does not renew grace or overwrite a newer challenge outcome.
        solver_status = self.status()
        scoped_result_status = (
            self.scope_status(completion_scope)
            if completion_scope in CHALLENGE_SCOPES
            else solver_status
        )
        snapshot_status = str(cookie_snapshot.get("status") or "").strip().lower()
        auth_confirmation_pending = bool(
            not auth_state_confirmed and snapshot_status in {"pending", "running"}
        )
        result = {
            "ok": bool(auth_state_confirmed or auth_confirmation_pending),
            "action": "auth_complete",
            "source": source,
            "completion_id": completion_id,
            "auth_state_confirmed": auth_state_confirmed,
            "idempotent": bool(
                previously_confirmed or (already_clear and auth_state_confirmed)
            ),
            "manual_auth_completed": auth_state_confirmed,
            "auth_confirmation_pending": auth_confirmation_pending,
            "paused": bool(solver_status.get("paused")),
            "scope": completion_scope or None,
            "scope_paused": bool(scoped_result_status.get("paused")),
            "scope_manual_required": bool(scoped_result_status.get("manual_required")),
            "scope_force_reset_required": bool(
                scoped_result_status.get("force_reset_required")
            ),
            "scope_force_unlock_flag_exists": bool(
                completion_scope in CHALLENGE_SCOPES
                and os.path.exists(self.scope_flag_path(completion_scope))
            ),
            "runtime_state": self.runtime_label(),
            "captcha_solver": solver_status,
            "cookie_snapshot": cookie_snapshot,
        }
        if clear_error is not None:
            result["error"] = f"failed to clear force unlock flag: {clear_error}"
        elif receipt_error is not None:
            result["error"] = (
                f"failed to persist auth completion receipt: {receipt_error}"
            )
        elif finalization_error is not None:
            result["error"] = finalization_error
        elif previously_confirmed and not auth_state_confirmed:
            result["error"] = (
                "confirmed completion_id is stale for the current auth state"
            )
        elif snapshot_status == "failed":
            result["error"] = (
                "cookie snapshot refresh failed; collection remains paused"
            )
        elif snapshot_status == "completed" and not auth_state_confirmed:
            result["error"] = (
                "cookie snapshot completed but auth state could not be confirmed"
            )
        elif not auth_state_confirmed:
            result["pending_reason"] = "waiting for a healthy cookie snapshot"
        if recovery_error is not None:
            result["recovery_error"] = recovery_error
        return result

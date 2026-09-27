"""Native cookie-finalization and cooldown cleanup transactions."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from .auth_cleanup_journal import AuthCleanupIntent
from .auth_cleanup_recovery import legacy_cleanup_state, restore_auth_cleanup
from .collection_control_state import CHALLENGE_SCOPES
from .runtime_state import RuntimeState
from .solver_captcha_reports import ReportMarker
from .solver_pause_cleanup import PauseSetter


@dataclass(frozen=True)
class AuthCleanupCompletion:
    runtime: Callable[[], RuntimeState]
    normalize_scope: Callable[[object], str | None]
    scope_status: Callable[[str | None], dict[str, object]]
    infer_scope: Callable[[object], str | None]
    scope_for_id: Callable[[object], str | None]
    was_confirmed: Callable[[str | None], bool]
    status: Callable[[], dict[str, object]]
    confirmed: Callable[[dict[str, object], str | None], bool]
    read_scope: Callable[[str | None], dict[str, object]]
    flag_manual_only: Callable[[], bool]
    state_root: Callable[[], Path]
    clear_pause: Callable[[str | None], str | None]
    remember_confirmation: Callable[[str | None], str | None]
    remember_completion: Callable[[object], None]
    persist_scope: Callable[[str, Mapping[str, object]], str | None]
    persist_legacy: Callable[[str, dict[str, str]], str | None]
    write_manual_flag: Callable[[float], str | None]
    refresh_request: Callable[[dict[str, object]], object]
    begin: Callable[[object], str]
    mark_manual: ReportMarker
    manual_only: Callable[[object], bool]
    set_pause: PauseSetter
    normalize_completion: Callable[[object], str | None]
    paused: Callable[[], bool]
    node_matches: Callable[[dict[str, object], str], bool]
    build_request: Callable[[object], dict[str, str]]
    scope_flag_path: Callable[[str | None], str]
    runtime_label: Callable[[], str]

    __all__: ClassVar[list[str]] = [
        "_auth_state_is_confirmed",
        "_finalize_auth_completion_after_cookie_snapshot",
        "_node_auth_challenge_matches",
        "_collection_observer_resume_after_cooldown_payload",
    ]

    def _auth_state_is_confirmed(
        self, solver_status: dict[str, object], scope: str | None = None
    ) -> bool:
        normalized_scope = self.normalize_scope(scope)
        if normalized_scope:
            scoped = self.scope_status(normalized_scope)
            return bool(
                not scoped.get("paused")
                and not scoped.get("manual_required")
                and not scoped.get("force_reset_required")
            )
        return bool(
            not solver_status.get("paused")
            and not solver_status.get("running")
            and not solver_status.get("manual_required")
            and not solver_status.get("force_unlock_flag_exists")
        )

    def _finalize_auth_completion_after_cookie_snapshot(
        self,
        completion_id: str | None,
        *,
        expected_challenge_id: str | None,
        completion_request: dict[str, object] | None,
    ) -> dict[str, object]:
        """Clear a manual pause only after a healthy cookie snapshot is durable."""

        normalized_expected = str(expected_challenge_id or "").strip() or None
        # Scope fallback, challenge validation and cleanup share one publication boundary.
        with self.runtime().recovery.finalize_lock, self.runtime().lock:
            completion_scope = self.infer_scope(completion_request)
            if completion_scope not in CHALLENGE_SCOPES:
                completion_scope = self.scope_for_id(normalized_expected)
            if (
                completion_scope in CHALLENGE_SCOPES
                and not self.scope_status(completion_scope).get("challenge_id")
                and normalized_expected
                == str(self.runtime().recovery.snapshot().challenge_id or "").strip()
            ):
                completion_scope = None
            normalized_current = (
                str(
                    self.scope_status(completion_scope).get("challenge_id") or ""
                ).strip()
                or None
                if completion_scope in CHALLENGE_SCOPES
                else str(self.runtime().recovery.snapshot().challenge_id or "").strip()
                or None
            )
            if normalized_current != normalized_expected:
                return {
                    "auth_state_confirmed": False,
                    "stale_challenge": True,
                    "expected_challenge_id": normalized_expected,
                    "challenge_id": normalized_current,
                    "error": "cookie snapshot belongs to an older captcha challenge",
                }

            previously_confirmed = self.was_confirmed(completion_id)
            before_status = self.status()
            if previously_confirmed and self.confirmed(before_status, completion_scope):
                return {
                    "auth_state_confirmed": True,
                    "idempotent": True,
                    "challenge_id": normalized_current,
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
            receipt_error: str | None = None
            if auth_state_confirmed:
                receipt_error = self.remember_confirmation(completion_id)
                if receipt_error is None:
                    receipt_error = intent.finish()
                auth_state_confirmed = receipt_error is None

            if auth_state_confirmed:
                self.runtime().solver.record_outcome("manual_auth_completed")
                self.remember_completion(completion_request)
            else:
                recovery_error: str | None = None
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
                elif clear_error is None:
                    if isinstance(completion_request, dict) and completion_request:
                        self.refresh_request(completion_request)
                    self.begin(completion_request)
                    recovery_error = self.mark_manual(
                        manual_only=self.manual_only(completion_request),
                        scope=completion_scope or None,
                    )
                self.runtime().solver.record_outcome(
                    "manual_required", "manual_required"
                )
                self.set_pause(True, "manual_required")

            result: dict[str, object] = {
                "auth_state_confirmed": auth_state_confirmed,
                "idempotent": bool(previously_confirmed and auth_state_confirmed),
                "challenge_id": self.runtime().recovery.snapshot().challenge_id,
            }
            if clear_error is not None:
                result["error"] = f"failed to clear force unlock flag: {clear_error}"
            elif receipt_error is not None:
                result["error"] = (
                    f"failed to persist auth completion receipt: {receipt_error}"
                )
            elif not auth_state_confirmed:
                result["error"] = (
                    "auth state remained paused or manual_required after cleanup"
                )
            if not auth_state_confirmed and recovery_error is not None:
                result["recovery_error"] = recovery_error
            return result

    def _node_auth_challenge_matches(
        self, payload: dict[str, object], source: str
    ) -> bool:
        challenge_id = str(payload.get("challenge_id") or "").strip()
        scope = self.normalize_scope(payload.get("scope")) or self.scope_for_id(
            challenge_id
        )
        active_id = (
            str(self.scope_status(scope).get("challenge_id") or "").strip()
            if scope in CHALLENGE_SCOPES
            else str(self.runtime().recovery.snapshot().challenge_id or "").strip()
        )
        if source != "pc2_local_solver" or not active_id:
            return True
        return bool(challenge_id and challenge_id == active_id)

    def _collection_observer_resume_after_cooldown_payload(
        self,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Resume collection after a node-local cooldown without claiming a solve.

        The request id is recorded in the same durable receipt store as auth
        completions so a NAS timeout or PC2 restart can safely replay the request.
        """

        # Challenge matching, durable cleanup and receipt commit form one transaction.
        with self.runtime().lock:
            payload = payload if isinstance(payload, dict) else {}
            request_id = self.normalize_completion(payload.get("resume_request_id"))
            source = str(payload.get("source") or "pc2_local_solver")
            resume_scope = self.normalize_scope(
                payload.get("scope")
            ) or self.scope_for_id(payload.get("challenge_id"))
            if resume_scope not in CHALLENGE_SCOPES:
                reported_resume_id = str(payload.get("challenge_id") or "").strip()
                if (
                    reported_resume_id
                    and reported_resume_id
                    == str(
                        self.runtime().recovery.snapshot().challenge_id or ""
                    ).strip()
                ):
                    resume_scope = None
                else:
                    resume_scope = self.infer_scope(
                        self.runtime().recovery.snapshot().last_request
                    )
            if not request_id:
                return {
                    "ok": False,
                    "action": "resume_after_cooldown",
                    "source": source,
                    "resume_request_id": None,
                    "auth_state_confirmed": False,
                    "paused": bool(self.paused()),
                    "captcha_solver": self.status(),
                    "error": "resume_request_id is required",
                }
            if not self.node_matches(payload, source):
                solver_status = self.status()
                return {
                    "ok": False,
                    "action": "resume_after_cooldown",
                    "source": source,
                    "resume_request_id": request_id,
                    "auth_state_confirmed": False,
                    "stale_challenge": True,
                    "challenge_id": self.runtime().recovery.snapshot().challenge_id,
                    "paused": bool(solver_status.get("paused")),
                    "captcha_solver": solver_status,
                    "error": "resume request belongs to an older captcha challenge",
                }

            receipt_id = f"resume-after-cooldown:{request_id}"
            previously_confirmed = self.was_confirmed(receipt_id)
            before_status = self.status()
            already_clear = self.confirmed(before_status, resume_scope)
            recovery_before_cleanup = self.runtime().recovery.snapshot()
            cleanup_before = (
                self.read_scope(resume_scope)
                if resume_scope in CHALLENGE_SCOPES
                else legacy_cleanup_state(
                    recovery_before_cleanup,
                    manual_only=self.flag_manual_only(),
                )
            )
            clear_error: str | None = None
            receipt_error: str | None = None
            recovery_error: str | None = None
            if previously_confirmed:
                auth_state_confirmed = already_clear
            else:
                intent = AuthCleanupIntent(
                    self.state_root(),
                    resume_scope or None,
                    cleanup_before,
                    receipt_id,
                )
                clear_error = intent.prepare(read_scope=self.read_scope)
                if clear_error is None:
                    with intent.preserve_during_cleanup():
                        clear_error = self.clear_pause(resume_scope or None)
                cleared_status = self.status()
                auth_state_confirmed = clear_error is None and self.confirmed(
                    cleared_status, resume_scope
                )
                if auth_state_confirmed:
                    receipt_error = self.remember_confirmation(receipt_id)
                    if receipt_error is None:
                        receipt_error = intent.finish()
                    auth_state_confirmed = receipt_error is None
                    if receipt_error and (
                        cleanup_before.get("challenge_id")
                        or recovery_before_cleanup.challenge_id
                    ):
                        # Keep the original generation retryable after publication fails.
                        recovery_error = restore_auth_cleanup(
                            resume_scope,
                            cleanup_before,
                            recovery_before_cleanup,
                            runtime=self.runtime(),
                            persist_scope=self.persist_scope,
                            persist_legacy=self.persist_legacy,
                            write_manual_flag=self.write_manual_flag,
                        )

            if auth_state_confirmed:
                self.runtime().solver.record_outcome("resumed_after_cooldown")
                # The scoped clear can remove last_request before the grace baseline is
                # recorded. Keep the reporting node/CDP carried by the resume receipt,
                # then fill any missing target metadata from the retained server state.
                resume_request = self.build_request(payload)
                retained_request = self.runtime().recovery.snapshot().last_request
                if resume_scope in CHALLENGE_SCOPES:
                    scoped_request = self.scope_status(resume_scope).get("last_request")
                    if isinstance(scoped_request, dict) and scoped_request:
                        retained_request = scoped_request
                for key, value in self.build_request(retained_request).items():
                    resume_request.setdefault(key, value)
                self.remember_completion(resume_request)
            else:
                self.runtime().solver.record_outcome(
                    "manual_required", "manual_required"
                )
                self.set_pause(True, "manual_required", scope=resume_scope or None)
        solver_status = self.status()
        scoped_result_status = (
            self.scope_status(resume_scope)
            if resume_scope in CHALLENGE_SCOPES
            else solver_status
        )
        result: dict[str, object] = {
            "ok": auth_state_confirmed,
            "action": "resume_after_cooldown",
            "source": source,
            "resume_request_id": request_id,
            "auth_state_confirmed": auth_state_confirmed,
            "idempotent": bool(
                previously_confirmed or (already_clear and auth_state_confirmed)
            ),
            "manual_auth_completed": False,
            "paused": bool(solver_status.get("paused")),
            "scope": resume_scope or None,
            "scope_paused": bool(scoped_result_status.get("paused")),
            "scope_manual_required": bool(scoped_result_status.get("manual_required")),
            "scope_force_reset_required": bool(
                scoped_result_status.get("force_reset_required")
            ),
            "scope_force_unlock_flag_exists": bool(
                resume_scope in CHALLENGE_SCOPES
                and os.path.exists(self.scope_flag_path(resume_scope))
            ),
            "runtime_state": self.runtime_label(),
            "captcha_solver": solver_status,
            "cookie_snapshot": {"status": "skipped", "reason": "resume_after_cooldown"},
        }
        if clear_error is not None:
            result["error"] = f"failed to clear force unlock flag: {clear_error}"
        elif receipt_error is not None:
            result["error"] = f"failed to persist resume receipt: {receipt_error}"
        elif previously_confirmed and not auth_state_confirmed:
            result["error"] = (
                "confirmed resume_request_id is stale for the current auth state"
            )
        elif not auth_state_confirmed:
            result["error"] = (
                "auth state remained paused or manual_required after cleanup"
            )
        if recovery_error is not None:
            result["recovery_error"] = recovery_error
        return result

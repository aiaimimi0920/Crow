"""Native server solver lifecycle with late-bound runtime dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from .solver_run_contracts import SolverRequest, SolverRunHost

if TYPE_CHECKING:
    from .solver_execution_state import SolverExecution


@dataclass(frozen=True)
class SolverRunLifecycle:
    host: SolverRunHost

    def run_solver(
        self, solver_request: SolverRequest = None, submission_token: object = None
    ) -> None:
        """Run the captcha solver in background with server-level retry."""
        with self.host.RUNTIME.lock:
            preflight_execution = cast(
                "SolverExecution", self.host.RUNTIME.solver.current
            )
            preflight_pending = self.host.RUNTIME.solver.pending_token
        solver_scope = self.host._challenge_scope_for_request(solver_request)
        solver_status_snapshot = self.host._captcha_solver_runtime_status()
        scoped_snapshot = (
            self.host._solver_scope_runtime_status(solver_scope)
            if solver_scope in self.host.CHALLENGE_SCOPES
            else {}
        )
        if solver_scope in self.host.CHALLENGE_SCOPES and scoped_snapshot.get(
            "challenge_id"
        ):
            scope_requires_manual = bool(scoped_snapshot.get("manual_required"))
        elif solver_scope in self.host.CHALLENGE_SCOPES:
            latest_scope = self.host._challenge_scope_for_request(
                self.host.RUNTIME.recovery.snapshot().last_request
            )
            scope_requires_manual = bool(
                solver_status_snapshot.get("manual_required")
                if latest_scope not in self.host.CHALLENGE_SCOPES
                or latest_scope == solver_scope
                else False
            )
        else:
            scope_requires_manual = bool(solver_status_snapshot.get("manual_required"))
        if scope_requires_manual:
            already_authenticated = False
            try:
                probe_solver = self.host._build_solver_for_request(solver_request)
                preflight = probe_solver._preflight_current_challenge()
                already_authenticated = bool(preflight.get("already_authenticated"))
            except Exception:
                self.host.logger.exception("[SOLVER] Stale auth-lock preflight failed")
            if already_authenticated:
                with self.host.RUNTIME.lock:
                    if (
                        self.host.RUNTIME.solver.current is preflight_execution
                        and self.host.RUNTIME.solver.pending_token is preflight_pending
                    ):
                        self.host.logger.info(
                            "[SOLVER] Page already authenticated; clearing stale captcha auth lock."
                        )
                        self.host._clear_auth_lock_after_solver_success(
                            scope=solver_scope or None
                        )
                self.host._release_solver_submission(submission_token)
                return
            self.host._release_solver_submission(submission_token)
            self.host.logger.warning(
                "[SOLVER] Manual verification already required. Skipping solver run."
            )
            return
        with self.host.RUNTIME.lock:
            (activated, activation_reason, activation_value) = (
                self.host._activate_solver_submission(solver_request, submission_token)
            )
            execution = cast("SolverExecution", self.host.RUNTIME.solver.current)
        if not activated:
            if activation_reason == "solver_running":
                self.host.logger.info(
                    "[SOLVER] Solver already running for %ss. Skipping duplicate submission.",
                    int(activation_value),
                )
            else:
                self.host.logger.info(
                    "[SOLVER] Skipping %s solver submission.", activation_reason
                )
            return
        SERVER_MAX_ATTEMPTS = 2
        solver_started_at = activation_value
        solver_deadline = (
            self.host.time.monotonic() + self.host._solver_max_runtime_seconds()
        )

        def wait_for_window(seconds: float) -> bool:
            end = min(solver_deadline, self.host.time.monotonic() + seconds)
            while self.host.time.monotonic() < end:
                if self.host._solver_execution_cancelled(execution):
                    return False
                execution.cancelled.wait(
                    min(0.1, max(0.0, end - self.host.time.monotonic()))
                )
            return self.host.time.monotonic() < solver_deadline

        try:
            with self.host.RUNTIME.lock:
                if self.host._solver_execution_cancelled(execution):
                    return
                control = self.host.RUNTIME.control.snapshot()
                if not control.paused or control.reason is None:
                    self.host._set_collection_pause_state(
                        True, "captcha_solver", scope=solver_scope or None
                    )
            worker_quiesce_seconds = self.host._solver_worker_quiesce_seconds()
            if worker_quiesce_seconds > 0:
                self.host.logger.info(
                    "[SOLVER] Waiting %ss for node workers to release the shared CDP browser.",
                    worker_quiesce_seconds,
                )
                if not wait_for_window(worker_quiesce_seconds):
                    with self.host.RUNTIME.lock:
                        if not self.host._solver_execution_cancelled(execution):
                            self.host._mark_solver_manual_required(
                                scope=solver_scope or None
                            )
                            self.host.RUNTIME.solver.record_outcome(
                                "manual_required",
                                "deadline_exceeded",
                                execution=execution,
                            )
                    return
            if not self.host._wait_for_solver_cdp_ready(
                solver_request,
                deadline=solver_deadline,
                cancel_checker=lambda: self.host._solver_execution_cancelled(execution),
            ):
                with self.host.RUNTIME.lock:
                    if self.host._solver_execution_cancelled(execution):
                        return
                    self.host.logger.warning(
                        "[SOLVER] Deferring solve attempt because the node CDP browser is unavailable."
                    )
                    self.host._mark_solver_manual_required(scope=solver_scope or None)
                    failure_reason = (
                        "deadline_exceeded"
                        if self.host.time.monotonic() >= solver_deadline
                        else "cdp_unavailable"
                    )
                    self.host.RUNTIME.solver.record_outcome(
                        "manual_required", failure_reason, execution=execution
                    )
                return
            self.host.logger.info("[SOLVER] Starting solver...")
            active_solver = self.host._build_solver_for_request(solver_request)
            active_solver.solve_deadline = solver_deadline
            try:
                active_solver.cancel_checker = lambda: (
                    self.host._solver_execution_cancelled(execution)
                )
            except Exception:  # noqa: BLE001, S110 - optional legacy solver property
                pass
            if solver_request:
                self.host.logger.info(
                    "[SOLVER] Using request-scoped solver cdp_endpoint=%r target_url_set=%s",
                    solver_request.get("cdp_endpoint"),
                    bool(solver_request.get("target_url")),
                )
            success = False
            for server_attempt in range(SERVER_MAX_ATTEMPTS):
                if self.host._solver_execution_cancelled(execution):
                    break
                if self.host.time.monotonic() >= solver_deadline:
                    active_solver.last_failure_reason = "deadline_exceeded"
                    break
                if server_attempt > 0:
                    self.host.logger.info(
                        "[SOLVER] Server retry %s/%s after delay...",
                        server_attempt + 1,
                        SERVER_MAX_ATTEMPTS,
                    )
                    if not wait_for_window(3):
                        active_solver.last_failure_reason = (
                            "deadline_exceeded"
                            if self.host.time.monotonic() >= solver_deadline
                            else "cancelled"
                        )
                        break
                success = active_solver.solve()
                if success:
                    break
                if getattr(active_solver, "last_failure_reason", None) in {
                    "manual_required",
                    "cancelled",
                    "deadline_exceeded",
                }:
                    self.host.logger.warning(
                        "[SOLVER] Manual-required/cancelled failure detected; skipping server retry."
                    )
                    break
            with self.host.RUNTIME.lock:
                if not self.host._solver_execution_is_current(execution):
                    return
                if self.host._solver_execution_resumed(execution):
                    self.host.logger.info(
                        "[SOLVER] Manual resume happened after this solver started; suppressing stale failure pause."
                    )
                    self.host.RUNTIME.solver.record_outcome(
                        "resumed", execution=execution
                    )
                    self.host._set_collection_pause_state(
                        False, scope=solver_scope or None
                    )
                    return
                if self.host._solver_execution_cancelled(execution):
                    return
                if success:
                    self.host.logger.info("[SOLVER] Captcha solved; resuming system.")
                    self.host._clear_auth_lock_after_solver_success(
                        scope=solver_scope or None
                    )
                    return
                failure_reason = (
                    getattr(active_solver, "last_failure_reason", None)
                    or "solve_failed"
                )
                failure_status = (
                    "manual_required"
                    if failure_reason == "manual_required"
                    else "failed"
                )
                self.host.RUNTIME.solver.record_outcome(
                    failure_status, failure_reason, execution=execution
                )
                self.host.logger.error(
                    "[SOLVER] All solve attempts failed. System remains paused."
                )
                self.host.logger.warning(
                    "[SOLVER] Manual intervention required. Please solve in Edge, then click 'Resume' or delete 'force_unlock.flag'."
                )
                flag_error = self.host._mark_solver_manual_required(
                    scope=solver_scope or None
                )
                flag_path = self.host._solver_force_unlock_flag_path()
                if flag_error:
                    self.host.logger.error(
                        "[SOLVER] Failed to write force unlock flag: %s", flag_error
                    )
                self.host.RUNTIME.solver.finish(execution, self.host.time.time())

            if not success:

                def _current_solver_scope_manual_required() -> bool:
                    if solver_scope not in self.host.CHALLENGE_SCOPES:
                        return bool(
                            self.host._captcha_solver_runtime_status().get(
                                "manual_required"
                            )
                        )
                    scoped_status = self.host._solver_scope_runtime_status(solver_scope)
                    if scoped_status.get("challenge_id"):
                        return bool(scoped_status.get("manual_required"))
                    latest_scope = self.host._challenge_scope_for_request(
                        self.host.RUNTIME.recovery.snapshot().last_request
                    )
                    if (
                        latest_scope in self.host.CHALLENGE_SCOPES
                        and latest_scope != solver_scope
                    ):
                        return False
                    return bool(
                        self.host._captcha_solver_runtime_status().get(
                            "manual_required"
                        )
                    )

                while _current_solver_scope_manual_required():
                    if self.host.time.monotonic() >= solver_deadline:
                        # Persisted manual-required state is monitored by the runtime, not this expired worker.
                        break
                    with self.host.RUNTIME.lock:
                        if not self.host._solver_execution_is_current(
                            execution
                        ) or self.host._solver_execution_resumed(execution):
                            break
                        if not self.host.os.path.exists(flag_path):
                            self.host.logger.info(
                                "[SOLVER] Force unlock flag removed; auto-resuming system."
                            )
                            self.host._set_collection_pause_state(
                                False, scope=solver_scope or None
                            )
                            self.host._clear_solver_manual_required_state()
                            challenge_state_error = (
                                self.host._clear_solver_challenge_state(
                                    solver_scope or None
                                )
                            )
                            if challenge_state_error:
                                self.host.logger.error(
                                    "[SOLVER] Failed to clear persisted challenge state after force unlock: %s",
                                    challenge_state_error,
                                )
                            break
                    try:
                        preflight = active_solver._preflight_current_challenge()
                    except Exception as error:  # noqa: BLE001 - failed recovery probe remains manual
                        preflight = {}
                        self.host.logger.warning(
                            "[SOLVER] Auth-lock recovery preflight failed: %s", error
                        )
                    if preflight.get("already_authenticated"):
                        with self.host.RUNTIME.lock:
                            if self.host._solver_execution_is_current(
                                execution
                            ) and not self.host._solver_execution_resumed(execution):
                                self.host.logger.info(
                                    "[SOLVER] Page authenticated while waiting; clearing captcha auth lock."
                                )
                                self.host._clear_auth_lock_after_solver_success(
                                    scope=solver_scope or None
                                )
                        break
                    if not self.host._wait_for_solver_manual_poll(
                        execution, solver_deadline
                    ):
                        break
        except Exception as e:
            with self.host.RUNTIME.lock:
                if not self.host._solver_execution_cancelled(execution):
                    self.host.RUNTIME.solver.record_outcome(
                        "error", str(e), execution=execution
                    )
            self.host.logger.exception("[SOLVER] Error: %s", e)  # noqa: TRY401 - legacy log contract
        finally:
            finished_at = self.host.time.time()
            with self.host.RUNTIME.lock:
                is_current_solver_run = self.host.RUNTIME.solver.finish(
                    execution, finished_at
                )
            if not is_current_solver_run:
                self.host.logger.info(
                    "[SOLVER] Run was cleared or superseded; leaving current state unchanged."
                )
            started_for_log = solver_started_at
            elapsed = (
                max(finished_at - started_for_log, 0) if started_for_log > 0 else 0
            )
            self.host.logger.info("[SOLVER] Finished. Total time: %.1fs", elapsed)

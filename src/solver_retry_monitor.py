"""Manual retry monitoring with explicit live runtime and effect dependencies."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar, Protocol

from .collection_control_state import CHALLENGE_SCOPES
from .runtime_state import RuntimeState
from .server_solver_state import PauseCleaner
from .solver_status_reader import ScopeStatus

SubmitSolver = Callable[[dict[str, object]], object]


class ManualMarker(Protocol):
    def __call__(self, *, scope: str | None = None) -> str | None: ...


class RetryStatus(Protocol):
    def __call__(self, *, now: float | None = None) -> dict[str, object]: ...


class RetryRunner(Protocol):
    def __call__(
        self, *, now: float | None = None, submit_solver: SubmitSolver | None = None
    ) -> dict[str, object]: ...


QueueRetry = Callable[
    [dict[str, object], str | None, float, SubmitSolver | None], dict[str, object]
]


@dataclass(frozen=True)
class SolverRetryMonitor:
    runtime: Callable[[], RuntimeState]
    clock: Callable[[], float]
    enabled: Callable[[], bool]
    pending: Callable[[], bool]
    max_runtime: Callable[[], int]
    mark_manual: ManualMarker
    infer_scope: Callable[[object], str | None]
    status: RetryStatus
    request: Callable[[], dict[str, object]]
    delegated: Callable[[object], bool]
    next_retry: Callable[[float], float | None]
    probe: Callable[[str], bool]
    clear_pause: PauseCleaner
    scope_status: ScopeStatus
    set_pause: Callable[[bool], None]
    submit: SubmitSolver
    run_retry: RetryRunner
    queue_retry: QueueRetry

    __all__: ClassVar[list[str]] = [
        "_trigger_manual_solver_retry_if_due",
        "_run_manual_solver_retry_if_due",
        "_queue_manual_solver_retry",
    ]

    def _trigger_manual_solver_retry_if_due(
        self,
        *,
        now: float | None = None,
        submit_solver: SubmitSolver | None = None,
    ) -> dict[str, object]:
        if not self.runtime().retry_lock.acquire(blocking=False):
            return {"queued": False, "reason": "retry_pending"}
        try:
            return self.run_retry(now=now, submit_solver=submit_solver)
        finally:
            self.runtime().retry_lock.release()

    def _run_manual_solver_retry_if_due(
        self,
        *,
        now: float | None = None,
        submit_solver: SubmitSolver | None = None,
    ) -> dict[str, object]:
        current_time = self.clock() if now is None else now
        with self.runtime().lock:
            recovery_before = self.runtime().recovery.snapshot()
            control_before = self.runtime().control.snapshot()
            execution_before = self.runtime().solver.snapshot()
        if control_before.reason == "operator":
            return {"queued": False, "reason": "operator_paused"}
        if not self.enabled():
            return {"queued": False, "reason": "disabled"}
        if self.pending():
            return {"queued": False, "reason": "solver_pending"}
        execution = self.runtime().solver.snapshot()
        if execution.running:
            elapsed_seconds = (
                max(int(current_time - execution.started_at), 0)
                if execution.started_at
                else 0
            )
            max_runtime_seconds = self.max_runtime()
            if elapsed_seconds >= max_runtime_seconds:
                flag_error = self.mark_manual(
                    scope=self.infer_scope(
                        self.runtime().recovery.snapshot().last_request
                    )
                    or None
                )
                result: dict[str, object] = {
                    "queued": False,
                    "reason": "running_solver_timed_out",
                    "elapsed_seconds": elapsed_seconds,
                    "max_runtime_seconds": max_runtime_seconds,
                }
                if flag_error:
                    result["flag_error"] = flag_error
                return result
            return {
                "queued": False,
                "reason": "solver_running",
                "elapsed_seconds": elapsed_seconds,
                "max_runtime_seconds": max_runtime_seconds,
            }

        solver_status = self.status(now=current_time)
        if not solver_status.get("manual_required"):
            return {"queued": False, "reason": "not_manual_required"}

        solver_request = self.request()
        if not solver_request.get("target_url"):
            return {"queued": False, "reason": "missing_target_url"}
        solver_scope = self.infer_scope(solver_request)

        # PC2 owns its browser and runs the persistent 20s/10-attempt state
        # machine. The NAS monitor must not clear its manual pause or submit a
        # competing central solver request.
        if self.delegated(solver_request):
            return {
                "queued": False,
                "reason": "delegated_to_node_solver",
                "solver_request": solver_request,
            }

        next_retry_epoch = self.next_retry(current_time)
        if next_retry_epoch is not None and current_time < next_retry_epoch:
            return {
                "queued": False,
                "reason": "cooldown_active",
                "next_retry_epoch": next_retry_epoch,
            }

        # CDP 掉线时直接跳过本轮：保留 manual_required，不清 pause、不投 solver。
        # 只吃掉一个 cooldown，这样探测按 retry interval 走而不是每轮轮询都打一次。
        retry_cdp_endpoint = (
            str(solver_request.get("cdp_endpoint") or "").strip().rstrip("/")
        )
        healthy = self.probe(retry_cdp_endpoint)
        with self.runtime().lock:
            if (
                self.runtime().recovery.snapshot() != recovery_before
                or self.runtime().control.snapshot() != control_before
                or self.runtime().solver.snapshot() != execution_before
            ):
                return {"queued": False, "reason": "state_changed"}
            if not healthy:
                self.runtime().recovery.record_retry(current_time, attempted=False)
                return {
                    "queued": False,
                    "reason": "cdp_endpoint_unhealthy",
                    "cdp_endpoint": retry_cdp_endpoint,
                }
            return self.queue_retry(
                solver_request, solver_scope, current_time, submit_solver
            )

    def _queue_manual_solver_retry(
        self,
        solver_request: dict[str, object],
        solver_scope: str | None,
        current_time: float,
        submit_solver: SubmitSolver | None,
    ) -> dict[str, object]:
        clear_error = self.clear_pause(scope=solver_scope or None)
        if clear_error:
            return {
                "queued": False,
                "reason": "clear_manual_required_failed",
                "error": clear_error,
            }
        if (
            solver_scope in CHALLENGE_SCOPES
            and self.runtime().control.snapshot().reason
            in {"captcha_solver", "manual_required"}
            and not any(
                self.scope_status(other).get("paused")
                for other in CHALLENGE_SCOPES
                if other != solver_scope
            )
        ):
            # A retry is a transient hand-off: the worker will establish its own
            # scoped pause when it observes the next challenge.
            self.set_pause(False)

        with self.runtime().lock:
            self.runtime().recovery.record_retry(current_time, attempted=True)
            self.runtime().solver.record_outcome("manual_retry_queued")

        try:
            submit_result = (submit_solver or self.submit)(solver_request)
        except Exception as error:  # noqa: BLE001 - restore manual pause after submission failure
            self.mark_manual(scope=solver_scope or None)
            return {
                "queued": False,
                "reason": "submit_failed",
                "error": repr(error),
            }
        if submit_solver is None and submit_result is False:
            self.mark_manual(scope=solver_scope or None)
            return {
                "queued": False,
                "reason": "solver_active",
            }

        return {
            "queued": True,
            "reason": "manual_required_retry_due",
            "attempt": self.runtime().recovery.snapshot().retry_attempts,
            "solver_request": solver_request,
        }

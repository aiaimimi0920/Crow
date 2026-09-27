"""Read solver and scoped collection status from explicit live providers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Protocol

from .collection_control_state import CHALLENGE_SCOPES

if TYPE_CHECKING:
    from .runtime_state import RuntimeState


class ScopeStatus(Protocol):
    def __call__(
        self, scope: str, *, now: float | None = None
    ) -> dict[str, object]: ...


@dataclass(frozen=True)
class SolverStatusReader:
    runtime: Callable[[], RuntimeState]
    clock: Callable[[], float]
    flag_exists: Callable[[], bool]
    flag_request: Callable[[], dict[str, object]]
    scope_status: ScopeStatus
    infer_scope: Callable[[object], str | None]
    flag_manual_only: Callable[[], bool]
    target_manual_only: Callable[[object], bool]
    delegated: Callable[[object], bool]
    next_retry: Callable[[float], float | None]
    auto_enabled: Callable[[], bool]
    paused: Callable[[], bool]
    retry_enabled: Callable[[], bool]
    retry_interval: Callable[[], int]
    max_runtime: Callable[[], int]
    cookie_status: Callable[[], dict[str, object]]

    __all__: ClassVar[tuple[str, ...]] = ("_captcha_solver_runtime_status",)

    def _captcha_solver_runtime_status(
        self, now: float | None = None
    ) -> dict[str, object]:
        current_time = self.clock() if now is None else now
        with self.runtime().lock:
            execution = self.runtime().solver.snapshot()
            recovery = self.runtime().recovery.snapshot()
            pause = self.runtime().control.snapshot()
            active_run = execution.running
            queued = execution.pending_token is not None
            started_at = float(execution.started_at or 0)
            last_status = execution.last_status
            last_failure_reason = execution.failure_reason
            last_finished_at = execution.finished_at
            last_request: Mapping[str, object] = recovery.last_request
            paused = pause.paused
            pause_reason = pause.reason
            manual_only_flag = recovery.manual_only
            challenge_id = recovery.challenge_id
        running = bool(active_run or queued)
        force_unlock_flag_exists = self.flag_exists()
        if not last_request and force_unlock_flag_exists:
            last_request = self.flag_request()
        elapsed_seconds = (
            max(int(current_time - started_at), 0)
            if active_run and started_at > 0
            else 0
        )
        # Persisted stage challenges survive an idle legacy singleton/API restart.
        scope_statuses = {
            scope: self.scope_status(scope, now=current_time)
            for scope in CHALLENGE_SCOPES
        }
        active_scope = self.infer_scope(last_request)
        if active_scope not in CHALLENGE_SCOPES:
            active_scope = next(
                (
                    scope
                    for scope, status in scope_statuses.items()
                    if status.get("challenge_id")
                ),
                None,
            )
        selected_scope = scope_statuses.get(active_scope or "", {})
        manual_required = bool(
            force_unlock_flag_exists
            or (paused and last_status == "manual_required")
            or any(status.get("manual_required") for status in scope_statuses.values())
        )
        scoped_manual_only = (
            bool(selected_scope.get("manual_only")) if selected_scope else False
        )
        manual_only = bool(
            scoped_manual_only
            or (
                active_scope not in CHALLENGE_SCOPES
                and (manual_only_flag or self.flag_manual_only())
            )
            or self.target_manual_only(last_request)
        )
        delegated_to_node = bool(last_request and self.delegated(last_request))
        request_node_id = str(last_request.get("node_id") or "").strip().lower()
        request_owner = (
            (request_node_id or "node")
            if delegated_to_node
            else ("nas" if last_request else None)
        )
        execution_mode = (
            "manual"
            if manual_only
            else "delegated_node"
            if delegated_to_node
            else "nas_local"
            if last_request
            else "idle"
        )
        manual_retry_next_epoch = (
            self.next_retry(current_time) if manual_required else None
        )
        return {
            "running": running,
            "queued": queued,
            "started_at_epoch": started_at if started_at > 0 else None,
            "elapsed_seconds": elapsed_seconds,
            "last_status": last_status,
            "last_failure_reason": last_failure_reason,
            "last_finished_at_epoch": last_finished_at if last_finished_at else None,
            "manual_required": manual_required,
            "manual_only": manual_only,
            "execution_mode": execution_mode,
            "request_owner": request_owner,
            "delegated_to_node_solver": delegated_to_node,
            "nas_solver_active": running,
            "node_solver_expected": bool(delegated_to_node and not manual_only),
            "real_taobao_auto_solver_enabled": self.auto_enabled(),
            "force_unlock_flag_exists": force_unlock_flag_exists,
            "paused": bool(
                self.paused()
                or any(status.get("paused") for status in scope_statuses.values())
            ),
            "pause_reason": pause_reason,
            "last_request": last_request,
            "manual_retry_enabled": self.retry_enabled(),
            "manual_retry_interval_seconds": self.retry_interval(),
            "solver_max_runtime_seconds": self.max_runtime(),
            "manual_retry_attempts": recovery.retry_attempts,
            "manual_retry_last_epoch": recovery.retry_last_epoch or None,
            "manual_retry_next_epoch": manual_retry_next_epoch,
            "challenge_id": challenge_id,
            "cookie_snapshot_refresh": self.cookie_status(),
            # New consumers use these independent state machines.  The legacy
            # singleton fields above remain for older workers and API clients.
            "scope": active_scope or None,
            "scopes": scope_statuses,
            "collection_scopes": scope_statuses,
            "collection_pause_markers": {
                scope: "paused"
                if bool(status.get("paused") or status.get("manual_required"))
                else "collecting"
                for scope, status in scope_statuses.items()
            },
        }

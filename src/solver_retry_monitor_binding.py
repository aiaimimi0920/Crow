"""Compose retry monitoring against the current server facade dependencies."""

from collections.abc import Callable
from typing import Protocol

from .runtime_state import RuntimeState
from .server_solver_state import PauseCleaner
from .solver_pause_cleanup import PauseSetter
from .solver_retry_monitor import (
    ManualMarker,
    QueueRetry,
    RetryRunner,
    RetryStatus,
    SolverRetryMonitor,
    SubmitSolver,
)
from .solver_status_reader import ScopeStatus


class RetryClock(Protocol):
    time: Callable[[], float]


class RetryMonitorHost(Protocol):
    RUNTIME: RuntimeState
    time: RetryClock
    _manual_solver_retry_enabled: Callable[[], bool]
    _solver_submission_pending: Callable[[], bool]
    _solver_max_runtime_seconds: Callable[[], int]
    _mark_solver_manual_required: ManualMarker
    _challenge_scope_for_request: Callable[[object], str | None]
    _captcha_solver_runtime_status: RetryStatus
    _manual_solver_retry_request: Callable[[], dict[str, object]]
    _solver_request_delegated_to_node: Callable[[object], bool]
    _manual_solver_retry_next_epoch: Callable[[float], float | None]
    _probe_solver_cdp_endpoint: Callable[[str], bool]
    _clear_solver_manual_required_pause: PauseCleaner
    _solver_scope_runtime_status: ScopeStatus
    _set_collection_pause_state: PauseSetter
    _submit_solver_request: SubmitSolver
    _run_manual_solver_retry_if_due: RetryRunner
    _queue_manual_solver_retry: QueueRetry


def bind_solver_retry_monitor(host: RetryMonitorHost) -> SolverRetryMonitor:
    return SolverRetryMonitor(
        runtime=lambda: host.RUNTIME,
        clock=lambda: host.time.time(),
        enabled=lambda: host._manual_solver_retry_enabled(),
        pending=lambda: host._solver_submission_pending(),
        max_runtime=lambda: host._solver_max_runtime_seconds(),
        mark_manual=lambda **kwargs: host._mark_solver_manual_required(**kwargs),
        infer_scope=lambda request: host._challenge_scope_for_request(request),
        status=lambda **kwargs: host._captcha_solver_runtime_status(**kwargs),
        request=lambda: host._manual_solver_retry_request(),
        delegated=lambda request: host._solver_request_delegated_to_node(request),
        next_retry=lambda now: host._manual_solver_retry_next_epoch(now),
        probe=lambda endpoint: host._probe_solver_cdp_endpoint(endpoint),
        clear_pause=lambda **kwargs: host._clear_solver_manual_required_pause(**kwargs),
        scope_status=lambda scope, **kwargs: host._solver_scope_runtime_status(
            scope, **kwargs
        ),
        set_pause=lambda paused: host._set_collection_pause_state(paused),
        submit=lambda request: host._submit_solver_request(request),
        run_retry=lambda **kwargs: host._run_manual_solver_retry_if_due(**kwargs),
        queue_retry=lambda request, scope, now, submit: host._queue_manual_solver_retry(
            request, scope, now, submit
        ),
    )

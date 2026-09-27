"""Cancellation and poll ownership for an individual solver execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Protocol, cast

if TYPE_CHECKING:
    from .runtime_state import RuntimeState
    from .solver_execution_state import SolverExecution


class MonotonicClock(Protocol):
    def monotonic(self) -> float: ...


class SolverExecutionHost(Protocol):
    RUNTIME: RuntimeState
    time: MonotonicClock

    def _solver_execution_is_current(self, execution: SolverExecution) -> bool: ...
    def _solver_execution_resumed(self, execution: SolverExecution) -> bool: ...


@dataclass(frozen=True)
class SolverExecutionGuard:
    host: SolverExecutionHost
    __all__: ClassVar[list[str]] = [
        "_solver_execution_is_current",
        "_solver_execution_resumed",
        "_solver_execution_cancelled",
        "_wait_for_solver_manual_poll",
    ]

    def _solver_execution_is_current(self, execution: SolverExecution) -> bool:
        with self.host.RUNTIME.lock:
            return cast(
                bool,
                self.host.RUNTIME.solver.owns(execution)
                and self.host.RUNTIME.solver.started_at == execution.started_at,
            )

    def _solver_execution_resumed(self, execution: SolverExecution) -> bool:
        with self.host.RUNTIME.lock:
            return cast(
                bool,
                self.host.RUNTIME.recovery.snapshot().resume_epoch
                != execution.resume_epoch,
            )

    def _solver_execution_cancelled(self, execution: SolverExecution) -> bool:
        with self.host.RUNTIME.lock:
            return cast(
                bool,
                not self.host._solver_execution_is_current(execution)
                or execution.cancelled.is_set()
                or self.host._solver_execution_resumed(execution)
                or self.host.RUNTIME.recovery.snapshot().cancel_epoch
                != execution.cancel_epoch,
            )

    def _wait_for_solver_manual_poll(
        self, execution: SolverExecution, deadline: float
    ) -> bool:
        end = min(deadline, self.host.time.monotonic() + 2)
        while self.host.time.monotonic() < end:
            with self.host.RUNTIME.lock:
                if not self.host._solver_execution_is_current(
                    execution
                ) or self.host._solver_execution_resumed(execution):
                    return False
            if execution.superseded.wait(
                min(0.1, max(0.0, end - self.host.time.monotonic()))
            ):
                return False
        return self.host.time.monotonic() < deadline

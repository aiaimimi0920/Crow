"""Cooperative solver deadline and cancellation, including lock acquisition."""
from __future__ import annotations

from _thread import LockType
from contextlib import contextmanager
import math
from threading import Event
import time
from typing import Callable, Iterator, Protocol

from src.project_environment import getenv as project_getenv


class SolveStopped(Exception):
    pass


class BudgetedSolver(Protocol):
    lock: LockType
    _solve_budget: SolveBudget | None
    last_failure_reason: str | None

    def _cancel_requested(self) -> bool: ...
    def _close_solver_ws(self) -> object: ...
    def _close_owned_target_tabs(self) -> object: ...


class SolveBudget:
    def __init__(self, *, deadline: float | None = None, cancel_event: Event | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        if deadline is None:
            raw_seconds = project_getenv("CROW_SOLVER_MAX_RUNTIME_SECONDS", "180")
            try:
                seconds = float(raw_seconds)
            except ValueError:
                seconds = 180.0
            if not math.isfinite(seconds) or seconds <= 0:
                seconds = 180.0
            deadline = clock() + seconds
        self.deadline = float(deadline)
        if not math.isfinite(self.deadline):
            raise ValueError("Solver deadline must be finite")
        self.event = cancel_event if cancel_event is not None else Event()
        self.reason: str | None = None

    def remaining(self) -> float:
        return max(0.0, self.deadline - self.clock())

    def stopped(self, checker: Callable[[], bool] | None = None) -> bool:
        if self.event.is_set() or (checker is not None and checker()):
            self.reason = "cancelled"
        elif self.remaining() <= 0:
            self.reason = "deadline_exceeded"
        return self.reason is not None

    def wait(self, seconds: float, checker: Callable[[], bool] | None = None) -> None:
        end = min(self.deadline, self.clock() + max(0.0, seconds))
        while not self.stopped(checker):
            remaining = end - self.clock()
            if remaining <= 0:
                return
            self.event.wait(min(remaining, 0.1))
        raise SolveStopped(self.reason)

    @contextmanager
    def scope(self, solver: BudgetedSolver) -> Iterator[None]:
        while not solver.lock.acquire(blocking=False):
            self.wait(0.05, solver._cancel_requested)
        try:
            solver._solve_budget = self
            try:
                yield
            except SolveStopped:
                solver.last_failure_reason = self.reason or "deadline_exceeded"
                solver._close_solver_ws()
                solver._close_owned_target_tabs()
                raise
        finally:
            solver._solve_budget = None
            solver.lock.release()

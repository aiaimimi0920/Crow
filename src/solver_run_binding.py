"""Handler-compatible function wrapper around the native solver lifecycle."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar

from .solver_run_contracts import SolverRequest, SolverRunHost
from .solver_run_lifecycle import SolverRunLifecycle


@dataclass(frozen=True)
class SolverRunBinding:
    run_solver: Callable[..., None]
    __all__: ClassVar[list[str]] = ["run_solver"]


def bind_solver_run(host: SolverRunHost) -> SolverRunBinding:
    owner = SolverRunLifecycle(host)

    def run_solver(
        handler: object,
        solver_request: SolverRequest = None,
        submission_token: object = None,
    ) -> None:
        owner.run_solver(solver_request, submission_token)

    return SolverRunBinding(run_solver)

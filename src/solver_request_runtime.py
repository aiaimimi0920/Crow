"""Solver request ownership with explicit runtime and factory dependencies."""

from typing import Protocol, TypeVar

from src.runtime_state import RuntimeState
from src.solver_request_payload import (
    _build_solver_request,
    _normalize_solver_cdp_endpoint,
)

SolverT = TypeVar("SolverT")
SolverT_co = TypeVar("SolverT_co", covariant=True)


class SolverFactory(Protocol[SolverT_co]):
    def __call__(self, *, cdp_endpoint: str, target_url: object) -> SolverT_co: ...


def refresh_solver_last_request(
    request_payload: object, *, runtime: RuntimeState
) -> dict[str, str]:
    request = _build_solver_request(request_payload)
    with runtime.lock:
        merged: dict[str, str] = runtime.recovery.snapshot().last_request
        if not request:
            return merged
        merged.update(request)
        updated: dict[str, str] = runtime.recovery.set_request(
            _build_solver_request(merged)
        )
        return updated


def build_solver_for_request(
    request_payload: object,
    *,
    default_solver: SolverT,
    factory: SolverFactory[SolverT],
) -> SolverT:
    if request_payload and isinstance(request_payload, dict):
        target_url = request_payload.get("challenge_target_url") or request_payload.get(
            "target_url"
        )
        if request_payload.get("cdp_endpoint") or target_url:
            return factory(
                cdp_endpoint=_normalize_solver_cdp_endpoint(
                    request_payload.get("cdp_endpoint")
                ),
                target_url=target_url,
            )
    return default_solver

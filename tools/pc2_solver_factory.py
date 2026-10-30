"""Lazy solver construction and the interface required by the PC2 executor."""

from __future__ import annotations

from typing import Protocol, cast


class ExecutionSolver(Protocol):
    last_failure_reason: str | None

    def __init__(self, *, cdp_endpoint: str, target_url: str) -> None: ...

    def _remember_target_tab(self, tab: dict[str, object]) -> None: ...

    def solve(
        self,
        *,
        max_attempts: int,
        nc_retry_replay_limit: int,
        slider_find_max_retries: int,
        drag_profile_offset: int,
    ) -> bool: ...

    @staticmethod
    def _is_manual_challenge_url(value: object) -> bool: ...

    @staticmethod
    def _is_login_url(value: object) -> bool: ...

    def _open_keepalive_tab(self) -> str | None: ...

    def _close_cdp_target(self, target_id: str) -> bool: ...

    def _solver_target_scope(self, value: object) -> str: ...

    def _manual_challenge_matches_requested_target(self, value: object) -> bool: ...

    def _is_challenge_tab(self, tab: dict[str, object]) -> bool: ...

    def _open_target_tab(self) -> dict[str, object] | None: ...

    def _solver_target_route(self, value: object) -> str: ...


def solver_class() -> type[ExecutionSolver]:
    from src.captcha_solver import CaptchaSolver

    return cast(type[ExecutionSolver], CaptchaSolver)

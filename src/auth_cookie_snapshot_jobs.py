"""Bind cookie refresh jobs to explicit runtime and effect providers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Thread
from typing import TYPE_CHECKING, ClassVar

from .auth_cookie_snapshot_retry import Finalizer, StateWriter, run_snapshot_retry
from .auth_cookie_snapshot_scheduler import RetryRunner, schedule_refresh

if TYPE_CHECKING:
    from .auth_cookie_snapshot_state import AuthCookieSnapshotState


@dataclass(frozen=True)
class AuthCookieSnapshotJobs:
    state: Callable[[], AuthCookieSnapshotState]
    retry_attempts: Callable[[], int]
    retry_backoff: Callable[[], float]
    set_state: StateWriter
    refresh: Callable[[dict[str, object]], object]
    finalize: Finalizer
    retry_runner: Callable[[], RetryRunner]
    refresh_enabled: Callable[[dict[str, object]], bool]
    clock: Callable[[], float]
    sleep: Callable[[float], None]
    thread_factory: Callable[..., Thread]

    __all__: ClassVar[tuple[str, ...]] = (
        "_run_auth_cookie_snapshot_retry",
        "_schedule_auth_cookie_snapshot_refresh",
    )

    def _run_auth_cookie_snapshot_retry(
        self,
        payload: dict[str, object],
        completion_id: str | None,
        *,
        finalize_auth: bool = False,
        expected_challenge_id: str | None = None,
        completion_request: dict[str, object] | None = None,
    ) -> None:
        run_snapshot_retry(
            payload,
            completion_id,
            max_attempts=self.retry_attempts(),
            base_backoff=self.retry_backoff(),
            set_state=self.set_state,
            refresh=self.refresh,
            finalize=self.finalize,
            clock=self.clock,
            sleep=self.sleep,
            finalize_auth=finalize_auth,
            expected_challenge_id=expected_challenge_id,
            completion_request=completion_request,
        )

    def _schedule_auth_cookie_snapshot_refresh(
        self,
        payload: dict[str, object],
        completion_id: str | None,
        *,
        finalize_auth: bool = False,
        expected_challenge_id: str | None = None,
        completion_request: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return schedule_refresh(
            payload,
            completion_id,
            state=self.state(),
            retry_attempts=self.retry_attempts,
            run_retry=self.retry_runner(),
            clock=self.clock,
            thread_factory=self.thread_factory,
            refresh_enabled=self.refresh_enabled(payload),
            finalize_auth=finalize_auth,
            expected_challenge_id=expected_challenge_id,
            completion_request=completion_request,
        )

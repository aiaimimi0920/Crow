"""Single-flight cookie refresh scheduling with explicit runtime ownership."""

from __future__ import annotations

from collections.abc import Callable
from threading import Thread
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from .auth_cookie_snapshot_state import AuthCookieSnapshotState


class RetryRunner(Protocol):
    def __call__(
        self,
        payload: dict[str, object],
        completion_id: str | None,
        *,
        finalize_auth: bool,
        expected_challenge_id: str | None,
        completion_request: dict[str, object],
    ) -> None: ...


def schedule_refresh(
    payload: dict[str, object],
    completion_id: str | None,
    *,
    state: AuthCookieSnapshotState,
    retry_attempts: Callable[[], int],
    run_retry: RetryRunner,
    clock: Callable[[], float],
    thread_factory: Callable[..., Thread],
    refresh_enabled: bool = True,
    finalize_auth: bool = False,
    expected_challenge_id: str | None = None,
    completion_request: dict[str, object] | None = None,
) -> dict[str, object]:
    with state.lock:
        current = cast(dict[str, object], state.snapshot())
        if state.active_thread() is not None:
            current["retry_queued"] = True
            current["reason"] = "refresh_already_running"
            return current
        if not refresh_enabled:
            return cast(
                dict[str, object],
                state.update(
                    {
                        "status": "skipped",
                        "completion_id": completion_id,
                        "attempts": 0,
                        "max_attempts": 0,
                        "refreshed": False,
                        "retry_queued": False,
                        "next_retry_at_epoch": None,
                        "result": {"refreshed": False, "reason": "disabled_by_request"},
                    }
                ),
            )
        if (
            completion_id
            and current.get("completion_id") == completion_id
            and current.get("status") == "completed"
        ):
            return current
        state.replace(
            {
                "status": "pending",
                "completion_id": completion_id,
                "attempts": 0,
                "max_attempts": retry_attempts(),
                "refreshed": False,
                "retry_queued": True,
                "next_retry_at_epoch": clock(),
                "auth_finalize_requested": bool(finalize_auth),
                "expected_challenge_id": expected_challenge_id,
            }
        )
        try:
            thread = thread_factory(
                target=run_retry,
                args=(dict(payload), completion_id),
                kwargs={
                    "finalize_auth": bool(finalize_auth),
                    "expected_challenge_id": expected_challenge_id,
                    "completion_request": dict(completion_request or {}),
                },
                name="auth-cookie-snapshot-refresh",
                daemon=True,
            )
            state.set_thread(thread)
            scheduled = cast(dict[str, object], state.snapshot())
            thread.start()
        except Exception:
            state.set_thread(None)
            state.update(
                {
                    "status": "failed",
                    "refreshed": False,
                    "auth_state_confirmed": False,
                    "retry_queued": False,
                    "next_retry_at_epoch": None,
                    "last_finished_at_epoch": clock(),
                    "result": {
                        "refreshed": False,
                        "reason": "snapshot_worker_start_failed",
                    },
                }
            )
            raise
        return scheduled

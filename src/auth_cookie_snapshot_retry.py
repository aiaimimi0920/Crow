"""Cookie snapshot retry policy with explicit effects and time dependencies."""

from collections.abc import Callable
from threading import Event
from typing import Protocol


class StateWriter(Protocol):
    def __call__(self, **updates: object) -> object: ...


class Finalizer(Protocol):
    def __call__(
        self,
        completion_id: str | None,
        *,
        expected_challenge_id: str | None,
        completion_request: dict[str, object] | None,
    ) -> dict[str, object]: ...


def run_snapshot_retry(
    payload: dict[str, object],
    completion_id: str | None,
    *,
    max_attempts: int,
    base_backoff: float,
    set_state: StateWriter,
    refresh: Callable[[dict[str, object]], object],
    finalize: Finalizer,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    finalize_auth: bool = False,
    expected_challenge_id: str | None = None,
    completion_request: dict[str, object] | None = None,
    stop_event: Event | None = None,
) -> None:
    last_result: dict[str, object] = {"refreshed": False, "reason": "not_started"}

    def stopped(attempts: int) -> bool:
        if stop_event is None or not stop_event.is_set():
            return False
        set_state(
            status="failed",
            completion_id=completion_id,
            attempts=attempts,
            max_attempts=max_attempts,
            refreshed=last_result.get("refreshed") is True,
            auth_state_confirmed=False,
            retry_queued=False,
            next_retry_at_epoch=None,
            last_finished_at_epoch=clock(),
            result={"reason": "application_stopping"},
        )
        return True

    for attempt in range(1, max_attempts + 1):
        if stopped(attempt - 1):
            return
        set_state(
            status="running",
            completion_id=completion_id,
            attempts=attempt,
            max_attempts=max_attempts,
            refreshed=False,
            retry_queued=False,
            next_retry_at_epoch=None,
            last_started_at_epoch=clock(),
        )
        try:
            refreshed = refresh(payload)
            last_result = (
                dict(refreshed)
                if isinstance(refreshed, dict)
                else {
                    "refreshed": False,
                    "reason": "invalid_refresh_result",
                }
            )
        except Exception as error:  # noqa: BLE001 - preserve retry diagnostics for refresh failures.
            last_result = {"refreshed": False, "error": repr(error)}

        if stopped(attempt):
            return
        if last_result.get("refreshed") is True:
            auth_finalization = None
            if finalize_auth:
                try:
                    auth_finalization = finalize(
                        completion_id,
                        expected_challenge_id=expected_challenge_id,
                        completion_request=completion_request,
                    )
                except Exception:
                    # Do not leave a dead worker advertised as running or retry cleanup.
                    set_state(
                        status="failed",
                        completion_id=completion_id,
                        attempts=attempt,
                        max_attempts=max_attempts,
                        refreshed=True,
                        auth_state_confirmed=False,
                        retry_queued=False,
                        next_retry_at_epoch=None,
                        last_finished_at_epoch=clock(),
                        result={**last_result, "reason": "auth_finalization_failed"},
                    )
                    raise
                last_result["auth_finalization"] = auth_finalization
            set_state(
                status="completed",
                completion_id=completion_id,
                attempts=attempt,
                max_attempts=max_attempts,
                refreshed=True,
                retry_queued=False,
                next_retry_at_epoch=None,
                last_finished_at_epoch=clock(),
                auth_state_confirmed=bool(
                    auth_finalization
                    and auth_finalization.get("auth_state_confirmed") is True
                ),
                result=last_result,
            )
            return
        if last_result.get("reason") == "disabled_by_request":
            set_state(
                status="skipped",
                completion_id=completion_id,
                attempts=attempt,
                max_attempts=max_attempts,
                refreshed=False,
                retry_queued=False,
                next_retry_at_epoch=None,
                last_finished_at_epoch=clock(),
                result=last_result,
            )
            return
        if attempt < max_attempts:
            delay = min(base_backoff * (2 ** (attempt - 1)), 300.0)
            set_state(
                status="pending",
                completion_id=completion_id,
                attempts=attempt,
                max_attempts=max_attempts,
                refreshed=False,
                retry_queued=True,
                next_retry_at_epoch=clock() + delay,
                result=last_result,
            )
            if delay > 0:
                if stop_event is None:
                    sleep(delay)
                else:
                    stop_event.wait(delay)

    set_state(
        status="failed",
        completion_id=completion_id,
        attempts=max_attempts,
        max_attempts=max_attempts,
        refreshed=False,
        retry_queued=False,
        next_retry_at_epoch=None,
        last_finished_at_epoch=clock(),
        result=last_result,
    )

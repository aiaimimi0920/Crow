"""NAS authentication recovery monitoring and authenticated result handling."""

from __future__ import annotations

import hmac
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Protocol, cast

from .auth_recovery_progress import (
    ProgressRepository,
    captured_detail_count,
    pending_detail_count,
)
from .collection_control_state import CHALLENGE_SCOPES
from .server_solver_state import PauseCleaner
from .solver_status_reader import ScopeStatus

if TYPE_CHECKING:
    from .runtime_state import RuntimeState

logger = logging.getLogger(__name__)


class HeaderReader(Protocol):
    def get(self, key: str) -> object: ...


class RecoveryCoordinator(Protocol):
    enabled: bool

    def sample(
        self,
        captured_count: int | None,
        pending_detail_count: int,
        *,
        operator_paused: bool,
        recovery_signal: str | None,
        recovery_signal_stall_seconds: float,
        blocked_scopes: tuple[str, ...],
    ) -> dict[str, object]: ...

    def snapshot(self) -> dict[str, object]: ...

    def accept_stage_result(
        self,
        payload: dict[str, object],
        *,
        validate_and_clear: Callable[[dict[str, object]], str | None],
        captured_count: int | None,
    ) -> dict[str, object]: ...

    def result(
        self, recovery_id: str, *, success: bool, reason: str
    ) -> dict[str, object]: ...


@dataclass(frozen=True)
class AuthRecovery:
    runtime: Callable[[], RuntimeState]
    repository: Callable[[], ProgressRepository]
    coordinator: Callable[[], RecoveryCoordinator]
    blocked_seconds: Callable[[], float]
    poll_seconds: Callable[[], float]
    sleep: Callable[[float], None]
    expected_token: Callable[[], str]
    solver_status: Callable[[], dict[str, object]]
    cookie_status: Callable[[], dict[str, object]]
    scope_status: ScopeStatus
    captured_count: Callable[[], int | None]
    pending_count: Callable[[], int]
    signal: Callable[[], str | None]
    sample: Callable[[], dict[str, object]]
    clear_pause: PauseCleaner
    matches_target: Callable[[str, str, dict[str, object]], bool]
    remember_completion: Callable[[dict[str, str]], None]
    paused: Callable[[], bool]

    __all__: ClassVar[tuple[str, ...]] = (
        "_solver_detail_captured_count",
        "_nas_auth_recovery_pending_detail_count",
        "_nas_auth_recovery_signal",
        "_sample_nas_auth_recovery",
        "_nas_auth_recovery_authorized",
        "nas_auth_recovery_watchdog_thread",
        "_nas_auth_recovery_result",
    )

    def _solver_detail_captured_count(self) -> int | None:
        return captured_detail_count(self.repository())

    def _nas_auth_recovery_pending_detail_count(self) -> int:
        return pending_detail_count(self.repository())

    def _nas_auth_recovery_signal(self) -> str | None:
        if self.runtime().control.snapshot().reason == "operator":
            return None
        solver_status = self.solver_status()
        if not solver_status.get("paused"):
            return None
        scoped_statuses = solver_status.get("scopes") or solver_status.get(
            "collection_scopes"
        )
        for scope in ("detail", "seed"):
            stage_status = (
                scoped_statuses.get(scope)
                if isinstance(scoped_statuses, dict)
                else None
            )
            try:
                challenge_age = float(
                    (stage_status or {}).get("challenge_age_seconds") or 0
                )
            except (TypeError, ValueError):
                challenge_age = 0.0
            if (
                isinstance(stage_status, dict)
                and stage_status.get("paused")
                and challenge_age >= self.blocked_seconds()
            ):
                return f"{scope}_challenge_stalled"
        if solver_status.get("manual_required"):
            return "captcha_manual_required"
        if isinstance(scoped_statuses, dict) and any(
            isinstance(status, dict)
            and status.get("paused")
            and status.get("node_solver_blocked")
            and status.get("node_solver_blocked_reason") == "repeated_solver_failures"
            for status in scoped_statuses.values()
        ):
            return "node_solver_retries_exhausted"
        snapshot_status = self.cookie_status()
        snapshot_result = snapshot_status.get("result")
        if not isinstance(snapshot_result, dict):
            snapshot_result = {}
        if (
            snapshot_status.get("status") == "failed"
            and snapshot_result.get("reason") == "cookie_snapshot_candidate_unhealthy"
        ):
            return "cookie_snapshot_candidate_unhealthy"
        return None

    def _sample_nas_auth_recovery(self) -> dict[str, object]:
        return self.coordinator().sample(
            self.captured_count(),
            self.pending_count(),
            operator_paused=self.runtime().control.snapshot().reason == "operator",
            recovery_signal=self.signal(),
            recovery_signal_stall_seconds=self.blocked_seconds(),
            blocked_scopes=tuple(
                scope
                for scope in CHALLENGE_SCOPES
                if self.scope_status(scope).get("challenge_id")
            ),
        )

    def _nas_auth_recovery_authorized(self, headers: HeaderReader) -> tuple[bool, str]:
        if not self.coordinator().enabled:
            return False, "auth recovery is disabled"
        expected = self.expected_token()
        supplied = str(headers.get("X-Fapai-Recovery-Token") or "").strip()
        if not expected:
            return False, "auth recovery token is not configured"
        if not supplied or not hmac.compare_digest(
            supplied.encode("utf-8"), expected.encode("utf-8")
        ):
            return False, "auth recovery token is invalid"
        return True, ""

    def nas_auth_recovery_watchdog_thread(self) -> None:
        while True:
            try:
                snapshot = self.sample()
                active = snapshot.get("active")
                if isinstance(active, dict) and active.get("status") == "requested":
                    logger.warning(
                        "[AUTH-RECOVERY] Collection stalled; PC1 authentication "
                        f"recovery requested ({active.get('recovery_id')}, "
                        f"trigger={active.get('trigger_reason')})."
                    )
            except Exception:
                logger.exception("[AUTH-RECOVERY] Watchdog sample failed")
            self.sleep(self.poll_seconds())

    def _nas_auth_recovery_result(
        self, payload: dict[str, object]
    ) -> dict[str, object]:
        recovery_id = str(payload.get("recovery_id") or "").strip()
        success = payload.get("success") is True
        reason = str(payload.get("reason") or "").strip()
        if not recovery_id:
            return {"ok": False, "error": "recovery_id is required"}
        snapshot = self.coordinator().snapshot()
        active = cast("dict[str, object]", snapshot.get("active") or {})
        last = cast("dict[str, object]", snapshot.get("last_result") or {})
        if active.get("scope") or (
            last.get("recovery_id") == recovery_id and last.get("scope")
        ):

            def validate_and_clear(recovery: dict[str, object]) -> str | None:

                scope = cast("str", recovery["scope"])
                with self.runtime().lock:
                    status = self.scope_status(scope)
                    current = str(status.get("challenge_id") or "")
                    if current and current != recovery.get("challenge_id"):
                        return "challenge_changed"
                    if not self.matches_target(
                        scope, cast("str", recovery.get("target_url")), status
                    ):
                        return "challenge_changed"
                    if self.runtime().control.snapshot().reason == "operator":
                        return "operator_pause_active"
                    return self.clear_pause(scope=scope, preserve_running_state=True)

            return self.coordinator().accept_stage_result(
                payload,
                validate_and_clear=validate_and_clear,
                captured_count=self.captured_count(),
            )
        if not success:
            return self.coordinator().result(
                recovery_id,
                success=False,
                reason=reason or "pc2_recovery_failed",
            )
        if self.runtime().control.snapshot().reason == "operator":
            return self.coordinator().result(
                recovery_id,
                success=False,
                reason="operator_pause_active",
            )

        result = self.coordinator().result(recovery_id, success=True, reason=reason)
        if not result.get("ok"):
            return result
        clear_error = self.clear_pause()
        if clear_error:
            self.coordinator().result(
                recovery_id,
                success=False,
                reason=f"clear_collection_pause_failed:{clear_error}",
            )
            return {"ok": False, "error": clear_error}
        self.remember_completion(
            {
                "node_id": "pc2",
                "source": "nas_auth_recovery",
            }
        )
        return {
            **result,
            "paused": self.paused(),
            "captcha_solver": self.solver_status(),
        }

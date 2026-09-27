"""Manual-only and delegated-node challenge report ownership."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar, Protocol, cast

from .collection_control_state import CHALLENGE_SCOPES
from .solver_pause_cleanup import PauseSetter


class PayloadFlag(Protocol):
    def __call__(self, payload: dict[str, object], key: str, default: bool) -> bool: ...


class ReportMarker(Protocol):
    def __call__(
        self, *, manual_only: bool = False, scope: str | None = None
    ) -> str | None: ...


@dataclass(frozen=True)
class SolverCaptchaReports:
    flag: PayloadFlag
    build_request: Callable[[object], dict[str, str]]
    refresh_request: Callable[[dict[str, str]], object]
    infer_scope: Callable[[object], str | None]
    begin: Callable[[object], str]
    mark_manual: ReportMarker
    status: Callable[[], dict[str, object]]
    read_scope: Callable[[str], dict[str, object]]
    clock: Callable[[], float]
    persist: Callable[[str, dict[str, object]], str | None]
    set_pause: PauseSetter

    __all__: ClassVar[list[str]] = [
        "_payload_flag",
        "_payload_force_solver_retry",
        "_payload_manual_only",
        "_manual_only_captcha_report_payload",
        "_node_solver_blocked_report_payload",
    ]

    def _payload_flag(
        self, payload: dict[str, object], key: str, default: bool
    ) -> bool:
        if key not in payload:
            return default
        value = payload.get(key)
        if isinstance(value, bool):
            return value
        text = str(value or "").strip().lower()
        if not text:
            return default
        return text not in {"0", "false", "no", "off"}

    def _payload_force_solver_retry(self, payload: dict[str, object]) -> bool:
        return any(
            self.flag(payload, key, False)
            for key in ("force_retry", "force_manual_retry", "operator_retry")
        )

    def _payload_manual_only(self, payload: dict[str, object]) -> bool:
        return self.flag(payload, "manual_only", False)

    def _manual_only_captcha_report_payload(
        self, payload: dict[str, object]
    ) -> dict[str, object]:
        solver_request = self.build_request(payload)
        if solver_request:
            self.refresh_request(solver_request)
        scope = self.infer_scope(solver_request)
        self.begin(solver_request)
        flag_error = self.mark_manual(manual_only=True, scope=scope or None)
        response_payload: dict[str, object] = {
            "status": "manual_required",
            "captcha_solver": self.status(),
        }
        if flag_error:
            response_payload["flag_error"] = flag_error
        return response_payload

    def _node_solver_blocked_report_payload(
        self, payload: dict[str, object]
    ) -> dict[str, object]:
        solver_request = self.build_request(payload)
        if solver_request:
            self.refresh_request(solver_request)
        scope = self.infer_scope(solver_request)
        if scope not in CHALLENGE_SCOPES:
            return {
                "status": "invalid_scope",
                "captcha_solver": self.status(),
            }

        self.begin(solver_request)
        state = self.read_scope(scope)
        blocked_at = float(
            cast("str | float", state.get("node_solver_blocked_at_epoch") or 0)
        )
        if blocked_at <= 0:
            blocked_at = self.clock()
        reason = str(payload.get("node_solver_blocked_reason") or "").strip()
        if reason != "repeated_solver_failures":
            reason = "repeated_solver_failures"
        try:
            attempts = max(
                int(
                    cast("str | int", payload.get("node_solver_blocked_attempts") or 0)
                ),
                0,
            )
        except (TypeError, ValueError):
            attempts = 0
        state.update(
            {
                "paused": True,
                "pause_reason": "manual_required",
                "manual_required": True,
                "manual_only": True,
                "last_status": "manual_required",
                "last_failure_reason": reason,
                "node_solver_blocked": True,
                "node_solver_blocked_at_epoch": blocked_at,
                "node_solver_blocked_reason": reason,
                "node_solver_blocked_attempts": max(
                    attempts,
                    int(
                        cast(
                            "str | int", state.get("node_solver_blocked_attempts") or 0
                        )
                    ),
                ),
            }
        )
        persist_error = self.persist(scope, state)
        self.set_pause(True, "manual_required", scope=scope)
        response: dict[str, object] = {
            "status": "node_solver_blocked",
            "scope": scope,
            "captcha_solver": self.status(),
        }
        if persist_error:
            response["state_error"] = persist_error
        return response

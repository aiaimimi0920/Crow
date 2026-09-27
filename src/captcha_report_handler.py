"""Captcha report admission with explicit live state and solver callbacks."""

from __future__ import annotations

import math
from collections.abc import Callable, Container
from dataclasses import dataclass
from logging import Logger
from typing import TYPE_CHECKING, ClassVar, Protocol, cast
from urllib.parse import urlparse

if TYPE_CHECKING:
    from .runtime_state import RuntimeState

Record = dict[str, object]
Request = dict[str, str]


class CaptchaReportHandler(Protocol):
    path: str

    def send_json(self, data: object) -> None: ...
    def send_error_json(
        self, *, status: int, code: str, message: str, details: Record
    ) -> None: ...


class ReportClock(Protocol):
    def time(self) -> float: ...


class CaptchaReportHost(Protocol):
    RUNTIME: RuntimeState
    CHALLENGE_SCOPES: Container[str]
    logger: Logger
    time: ReportClock

    def _read_json_body(self, handler: CaptchaReportHandler) -> tuple[bool, Record]: ...
    def _build_solver_request(self, payload: Record) -> Request: ...
    def _challenge_scope_for_request(self, request: Request) -> str: ...
    def _solver_report_stale_challenge_id(self, payload: Record) -> str | None: ...
    def _solver_report_predates_auth_completion(self, payload: Record) -> bool: ...
    def _solver_force_reset_report_suppression(
        self, request: Request
    ) -> Record | None: ...
    def _solver_auth_report_suppression(self, request: Request) -> Record | None: ...
    def _payload_flag(self, payload: Record, key: str, default: bool) -> bool: ...
    def _node_solver_blocked_report_payload(self, payload: Record) -> Record: ...
    def _payload_manual_only(self, payload: Record) -> bool: ...
    def _solver_target_requires_manual_only(self, request: Request) -> bool: ...
    def _manual_only_captcha_report_payload(self, payload: Record) -> Record: ...
    def _refresh_solver_last_request(self, request: Request) -> object: ...
    def _payload_force_solver_retry(self, payload: Record) -> bool: ...
    def _captcha_solver_runtime_status(self) -> Record: ...
    def _solver_scope_runtime_status(self, scope: str) -> Record: ...
    def _clear_solver_manual_required_pause(
        self, *, preserve_running_state: bool, scope: str | None
    ) -> str | None: ...
    def _solver_max_runtime_seconds(self) -> float: ...
    def _mark_solver_manual_required(self, *, scope: str | None) -> str | None: ...
    def _solver_cdp_endpoint_is_remote(self, endpoint: str) -> bool: ...
    def _begin_solver_challenge(self, request: Request) -> object: ...
    def _set_collection_pause_state(
        self, paused: bool, reason: str, *, scope: str | None
    ) -> object: ...
    def _submit_solver_request(self, request: Request) -> bool: ...


@dataclass(frozen=True)
class CaptchaReportHandlers:
    _post_captcha_report: Callable[[CaptchaReportHandler], None]
    __all__: ClassVar[list[str]] = ["_post_captcha_report"]


def bind_captcha_reports(host: CaptchaReportHost) -> CaptchaReportHandlers:
    def _post_captcha_report(handler: CaptchaReportHandler) -> None:
        accepted, payload = host._read_json_body(handler)
        if not accepted:
            return
        solver_request = host._build_solver_request(payload)
        challenge_scope = host._challenge_scope_for_request(solver_request)
        stale_challenge_id = host._solver_report_stale_challenge_id(payload)
        if stale_challenge_id:
            host.logger.warning(
                "[SOLVER] captcha report ignored; stale challenge id %r does not match the active challenge.",
                stale_challenge_id,
            )
            handler.send_json(
                {
                    "status": "stale_challenge",
                    "challenge_id": host.RUNTIME.recovery.snapshot().challenge_id,
                    "captcha_solver": host._captcha_solver_runtime_status(),
                }
            )
            return
        if host._solver_report_predates_auth_completion(payload):
            host.logger.info(
                "[SOLVER] captcha report ignored; it was created before the same node completed auth."
            )
            handler.send_json(
                {
                    "status": "stale_auth_report",
                    "captcha_solver": host._captcha_solver_runtime_status(),
                }
            )
            return
        force_reset_suppression = host._solver_force_reset_report_suppression(
            solver_request
        )
        if force_reset_suppression is not None:
            retry_after = max(
                0.0,
                float(cast("str | float", force_reset_suppression["grace_seconds"]))
                - float(cast("str | float", force_reset_suppression["age_seconds"])),
            )
            host.logger.info(
                "[SOLVER] report_captcha ignored after scoped force reset; scope=%s (%.0fs grace remaining).",
                force_reset_suppression["scope"],
                retry_after,
            )
            handler.send_json(
                {
                    "status": "recent_force_reset",
                    "reason": force_reset_suppression["reason"],
                    "scope": force_reset_suppression["scope"],
                    "retry_after_seconds": math.ceil(retry_after),
                    "captcha_solver": host._captcha_solver_runtime_status(),
                }
            )
            return
        auth_report_suppression = host._solver_auth_report_suppression(solver_request)
        if auth_report_suppression is not None:
            retry_after = max(
                0.0,
                float(cast("str | float", auth_report_suppression["grace_seconds"]))
                - float(cast("str | float", auth_report_suppression["age_seconds"])),
            )
            host.logger.info(
                "[SOLVER] report_captcha ignored after recent auth; reason=%s captured_since_auth=%s (%.0fs grace remaining).",
                auth_report_suppression["reason"],
                auth_report_suppression["captured_since_auth"],
                retry_after,
            )
            handler.send_json(
                {
                    "status": "recent_auth_complete",
                    "reason": auth_report_suppression["reason"],
                    "captured_since_auth": auth_report_suppression[
                        "captured_since_auth"
                    ],
                    "retry_after_seconds": math.ceil(retry_after),
                    "captcha_solver": host._captcha_solver_runtime_status(),
                }
            )
            return
        if host._payload_flag(payload, "node_solver_blocked", False):
            handler.send_json(host._node_solver_blocked_report_payload(payload))
            return
        manual_only = (
            urlparse(handler.path).path == "/api/report_manual_captcha"
            or host._payload_manual_only(payload)
            or host._solver_target_requires_manual_only(solver_request)
        )
        if manual_only:
            handler.send_json(host._manual_only_captcha_report_payload(payload))
            return
        if solver_request:
            host._refresh_solver_last_request(solver_request)
        force_retry = host._payload_force_solver_retry(payload)
        solver_status = host._captcha_solver_runtime_status()
        scope_status = (
            host._solver_scope_runtime_status(challenge_scope)
            if challenge_scope in host.CHALLENGE_SCOPES
            else solver_status
        )
        if scope_status.get("manual_required"):
            if force_retry:
                solver_was_running = bool(solver_status.get("running"))
                clear_error = host._clear_solver_manual_required_pause(
                    preserve_running_state=solver_was_running,
                    scope=challenge_scope or None,
                )
                if clear_error:
                    handler.send_error_json(
                        status=500,
                        code="AVM_CAPTCHA_SOLVER_FORCE_RETRY_FAILED",
                        message="清除验证码人工认证锁失败",
                        details={"error": clear_error},
                    )
                    return
                solver_status = host._captcha_solver_runtime_status()
                scope_status = (
                    host._solver_scope_runtime_status(challenge_scope)
                    if challenge_scope in host.CHALLENGE_SCOPES
                    else solver_status
                )
                host.logger.info(
                    "[SOLVER] report_captcha force retry cleared manual verification state."
                )
                if solver_was_running and host.RUNTIME.solver.snapshot().running:
                    handler.send_json(
                        {"status": "resuming", "captcha_solver": solver_status}
                    )
                    return
            else:
                host.logger.warning(
                    "[SOLVER] report_captcha ignored; manual verification is already required."
                )
                handler.send_json(
                    {"status": "manual_required", "captcha_solver": solver_status}
                )
                return
        if scope_status.get("manual_required"):
            host.logger.warning(
                "[SOLVER] report_captcha ignored; manual verification is already required."
            )
            handler.send_json(
                {"status": "manual_required", "captcha_solver": solver_status}
            )
            return
        if solver_status.get("queued"):
            host.logger.info(
                "[SOLVER] report_captcha ignored; solver submission is already queued."
            )
            handler.send_json(
                {
                    "status": "already_running",
                    "elapsed_seconds": 0,
                    "captcha_solver": solver_status,
                }
            )
            return
        execution = host.RUNTIME.solver.snapshot()
        if execution.running:
            elapsed = max(int(host.time.time() - (execution.started_at or 0)), 0)
            max_runtime_seconds = host._solver_max_runtime_seconds()
            if elapsed < max_runtime_seconds:
                host.logger.info(
                    "[SOLVER] report_captcha ignored; solver already running for %ss.",
                    elapsed,
                )
                handler.send_json(
                    {
                        "status": "already_running",
                        "elapsed_seconds": elapsed,
                        "captcha_solver": solver_status,
                    }
                )
                return
            host.logger.warning(
                "[SOLVER] report_captcha ignored; solver still running after %ss. Configured limit is %ss; marking manual verification required instead of starting a parallel solver.",
                elapsed,
                max_runtime_seconds,
            )
            flag_error = host._mark_solver_manual_required(
                scope=challenge_scope or None
            )
            response_payload: Record = {
                "status": "manual_required",
                "elapsed_seconds": elapsed,
                "captcha_solver": host._captcha_solver_runtime_status(),
            }
            if flag_error:
                response_payload["flag_error"] = flag_error
            handler.send_json(response_payload)
            return
        solver_cdp = str(solver_request.get("cdp_endpoint") or "").strip()
        if solver_cdp and host._solver_cdp_endpoint_is_remote(solver_cdp):
            node_id = str(solver_request.get("node_id") or "").strip()
            host._begin_solver_challenge(solver_request)
            host.logger.info(
                "[SOLVER] Remote CDP endpoint %s detected (node=%s); deferring to node-local solver. Pausing collection; node solver will clear when solved.",
                solver_cdp,
                node_id or "unknown",
            )
            host._set_collection_pause_state(
                True, "captcha_solver", scope=challenge_scope or None
            )
            handler.send_json(
                {
                    "status": "deferred_to_node_solver",
                    "captcha_solver": host._captcha_solver_runtime_status(),
                }
            )
            return
        host.logger.info("CAPTCHA REPORTED! Triggering Solver...")
        host._begin_solver_challenge(solver_request)
        try:
            queued = host._submit_solver_request(solver_request)
        except Exception as error:  # noqa: BLE001 - preserve queue error boundary
            handler.send_error_json(
                status=500,
                code="AVM_CAPTCHA_SOLVER_QUEUE_FAILED",
                message="验证码求解任务入队失败",
                details={"error": str(error)},
            )
            return
        if not queued:
            handler.send_json(
                {
                    "status": "already_running",
                    "elapsed_seconds": 0,
                    "captcha_solver": host._captcha_solver_runtime_status(),
                }
            )
            return
        handler.send_json({"status": "solving"})

    return CaptchaReportHandlers(_post_captcha_report)

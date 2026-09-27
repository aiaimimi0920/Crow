"""Native challenge state entrypoints with explicit runtime and effect ownership."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Protocol, cast

from .collection_control_state import CHALLENGE_SCOPES
from .solver_manual_pause import ManualFlagWriter
from .solver_pause_cleanup import PauseSetter

if TYPE_CHECKING:
    from .runtime_state import RuntimeState


class PauseCleaner(Protocol):
    def __call__(
        self, *, preserve_running_state: bool = False, scope: str | None = None
    ) -> str | None: ...


@dataclass(frozen=True)
class SolverState:
    runtime: Callable[[], RuntimeState]
    clock: Callable[[], float]
    new_id: Callable[[], str]
    source_scope: Callable[[str], str]
    logger: Callable[[], logging.Logger]
    build_request: Callable[[object], dict[str, str]]
    matches_source: Callable[[object, object], bool]
    infer_scope: Callable[[object], str | None]
    scope_status: Callable[[str], Mapping[str, object]]
    legacy_path: Callable[[], Path]
    read_legacy: Callable[[], Mapping[str, object]]
    root_path: Callable[[], Path]
    normalize_scope: Callable[[object], str | None]
    read_scope: Callable[[str], Mapping[str, object]]
    clear_locked: Callable[[str | None], str | None]
    scope_path: Callable[[str], Path]
    flag_path: Callable[[], str]
    set_pause: PauseSetter
    begin_locked: Callable[[object], str]
    persist_scope: Callable[[str, Mapping[str, object]], str | None]
    persist_legacy: Callable[[str, dict[str, str]], str | None]
    owner_key: Callable[[object], tuple[str, str]]
    request_key: Callable[[object], tuple[str, str, str]]
    effectively_paused: Callable[[], bool]
    runtime_status: Callable[[], dict[str, object]]
    last_target: Callable[[object], str]
    classify_target: Callable[[str], str]
    last_scope: Callable[[object], str]
    seed_pending: Callable[[dict[str, object]], bool]
    flag_scope: Callable[[], str | None]
    scope_flag_path: Callable[[str], str]
    clear_pause: PauseCleaner
    clear_challenge: Callable[[str | None], str | None]
    remember_completion: Callable[[dict[str, str]], None]
    clear_running: Callable[[], None]
    clear_manual: Callable[[], None]
    cancel: Callable[[], None]
    write_flag: ManualFlagWriter

    __all__: ClassVar[list[str]] = [
        "_solver_report_predates_auth_completion",
        "_solver_report_stale_challenge_id",
        "_persist_solver_challenge_state",
        "_scope_for_challenge_id",
        "_clear_solver_challenge_state",
        "_clear_solver_challenge_state_locked",
        "_restore_solver_challenge_state",
        "_restore_solver_scope_states",
        "_begin_solver_challenge",
        "_begin_solver_challenge_locked",
        "_solver_last_request_target_url",
        "_solver_request_scope_from_target_url",
        "_solver_last_request_scope",
        "_solver_request_scope",
        "_seed_stage_has_remaining_work",
        "_collection_runtime_state_label_from_status_payload",
        "_clear_auth_lock_after_solver_success",
        "_clear_solver_manual_required_state",
        "_clear_solver_running_state",
        "_request_solver_cancel",
        "_clear_solver_manual_required_pause",
        "_clear_solver_manual_required_pause_compat",
        "_mark_solver_manual_required",
    ]

    def _solver_request_scope_from_target_url(self, url: str) -> str:
        return self.source_scope(url)

    def _solver_report_predates_auth_completion(
        self,
        payload: dict[str, object] | None,
    ) -> bool:
        """Identify an in-flight worker report created before auth completed."""
        recovery = self.runtime().recovery.snapshot()
        completed_at = recovery.completed_at
        if completed_at <= 0 or not isinstance(payload, dict):
            return False
        raw_timestamp = payload.get("timestamp")
        if isinstance(raw_timestamp, bool):
            return False
        try:
            reported_at = float(cast("str | float", raw_timestamp))
        except (TypeError, ValueError):
            return False
        if reported_at > 10_000_000_000:
            reported_at /= 1000.0
        if reported_at <= 0 or reported_at > completed_at:
            return False

        completed = self.build_request(recovery.completed_request)
        incoming = self.build_request(payload)
        if not completed or not incoming:
            return False
        return self.matches_source(completed, incoming)

    def _solver_report_stale_challenge_id(
        self, payload: dict[str, object] | None
    ) -> str | None:
        if not isinstance(payload, dict):
            return None
        reported_challenge_id = str(payload.get("challenge_id") or "").strip()
        if not reported_challenge_id:
            return None
        scope = self.infer_scope(payload)
        if scope in CHALLENGE_SCOPES:
            active_challenge_id = str(
                self.scope_status(scope).get("challenge_id") or ""
            ).strip()
        else:
            active_challenge_id = str(
                self.runtime().recovery.snapshot().challenge_id or ""
            ).strip()
        if reported_challenge_id == active_challenge_id:
            return None
        return reported_challenge_id

    def _persist_solver_challenge_state(
        self, challenge_id: str, last_request: dict[str, object]
    ) -> str | None:
        from .solver_challenge_receipts import persist_legacy_challenge

        return persist_legacy_challenge(
            challenge_id,
            last_request,
            path=self.legacy_path(),
            read_legacy=self.read_legacy,
            clock=self.clock,
        )

    def _scope_for_challenge_id(self, challenge_id: str | None) -> str | None:
        from .solver_scope_runtime import find_challenge_scope

        return find_challenge_scope(challenge_id, self.scope_status)

    def _clear_solver_challenge_state(self, scope: str | None = None) -> str | None:
        """Clear one scoped challenge, or all challenge state for legacy callers."""
        from .solver_challenge_receipts import retire_and_clear

        return retire_and_clear(
            runtime=self.runtime(),
            directory=self.root_path,
            scope=self.normalize_scope(scope) or None,
            read_scope=self.read_scope,
            clear_locked=lambda: self.clear_locked(scope),
        )

    def _clear_solver_challenge_state_locked(self, scope: str | None) -> str | None:
        from .solver_challenge_receipts import clear_challenges_locked

        return clear_challenges_locked(
            runtime=self.runtime(),
            scope=self.normalize_scope(scope) or None,
            legacy_path=self.legacy_path,
            scoped_path=self.scope_path,
            read_legacy=self.read_legacy,
            read_scope=self.read_scope,
        )

    def _restore_solver_challenge_state(self) -> bool:
        from .solver_startup_recovery import restore_legacy_challenge

        return restore_legacy_challenge(
            runtime=self.runtime(),
            read_legacy=self.read_legacy,
            manual_flag_path=self.flag_path,
            set_pause=self.set_pause,
        )

    def _restore_solver_scope_states(self) -> bool:
        from .solver_startup_recovery import restore_scoped_challenges

        return restore_scoped_challenges(
            runtime=self.runtime(),
            read_scope=self.read_scope,
            set_pause=self.set_pause,
        )

    def _begin_solver_challenge(
        self, request_payload: dict[str, object] | None = None
    ) -> str:
        """Create/reuse the unique challenge latch for the request's collection scope."""
        with self.runtime().lock:
            return self.begin_locked(request_payload)

    def _begin_solver_challenge_locked(
        self, request_payload: dict[str, object] | None
    ) -> str:
        from .solver_challenge_creation import ChallengeCreation

        return ChallengeCreation(
            runtime=self.runtime(),
            build_request=self.build_request,
            request_scope=self.infer_scope,
            bind_root=self.root_path,
            read_scope=self.read_scope,
            read_legacy=self.read_legacy,
            persist_scope=self.persist_scope,
            persist_legacy=self.persist_legacy,
            owner_key=self.owner_key,
            request_key=self.request_key,
            effectively_paused=self.effectively_paused,
            set_pause=self.set_pause,
            clock=self.clock,
            new_id=self.new_id,
            logger=self.logger(),
        ).begin_locked(request_payload)

    def _solver_last_request_target_url(
        self, solver_status: dict[str, object] | None = None
    ) -> str:
        payload = (
            solver_status if isinstance(solver_status, dict) else self.runtime_status()
        )
        last_request = payload.get("last_request")
        if not isinstance(last_request, dict):
            return ""
        return str(
            last_request.get("target_url") or last_request.get("url") or ""
        ).strip()

    def _solver_last_request_scope(
        self, solver_status: dict[str, object] | None = None
    ) -> str:
        payload = (
            solver_status if isinstance(solver_status, dict) else self.runtime_status()
        )
        last_request = payload.get("last_request")
        if isinstance(last_request, dict):
            scoped = self.infer_scope(last_request)
            if scoped in CHALLENGE_SCOPES:
                return scoped
        return self.classify_target(self.last_target(payload))

    def _solver_request_scope(
        self, request_payload: dict[str, object] | None = None
    ) -> str:
        if not isinstance(request_payload, dict):
            return "unknown"
        target_url = (
            request_payload.get("target_url") or request_payload.get("url") or ""
        )
        return self.classify_target(str(target_url))

    def _seed_stage_has_remaining_work(self, status_payload: dict[str, object]) -> bool:
        return any(
            int(cast("str | int", status_payload.get(key, 0) or 0)) > 0
            for key in (
                "seed_scan_job_pending",
                "seed_scan_job_in_progress",
                "seed_scan_progress_pending",
                "seed_scan_progress_in_progress",
            )
        )

    def _collection_runtime_state_label_from_status_payload(
        self,
        status_payload: dict[str, object],
    ) -> str:
        solver_status = status_payload.get("captcha_solver")
        if not isinstance(solver_status, dict):
            solver_status = {}

        manual_required = bool(
            solver_status.get("manual_required")
            or solver_status.get("force_unlock_flag_exists")
        )
        if manual_required:
            if self.last_scope(solver_status) == "detail" and self.seed_pending(
                status_payload
            ):
                return "运行中"
            return "待认证"

        if bool(status_payload.get("paused")):
            return "暂停中"

        total_items = int(cast("str | int", status_payload.get("total_ids", 0) or 0))
        raw_pending = int(
            cast("str | int", status_payload.get("raw_capture_pending_count", 0) or 0)
        )
        detail_failed = int(
            cast("str | int", status_payload.get("detail_failed_count", 0) or 0)
        )
        detail_blocked = int(
            cast("str | int", status_payload.get("detail_blocked_count", 0) or 0)
        )
        analysis_pending = int(
            cast("str | int", status_payload.get("analysis_pending_count", 0) or 0)
        )
        analysis_blocked = int(
            cast("str | int", status_payload.get("analysis_blocked_count", 0) or 0)
        )
        if (
            total_items > 0
            and raw_pending == 0
            and detail_failed == 0
            and detail_blocked == 0
            and analysis_pending == 0
            and analysis_blocked == 0
        ):
            return "已完成"
        return "运行中"

    def _clear_auth_lock_after_solver_success(self, scope: str | None = None) -> None:
        """Release the completed scope without changing another challenge's pause."""
        from .solver_pause_cleanup import clear_automated_pause

        clear_automated_pause(
            runtime=self.runtime(),
            scope=self.normalize_scope(scope),
            infer_scope=self.infer_scope,
            read_scope=self.read_scope,
            read_legacy=self.read_legacy,
            flag_path=self.flag_path,
            flag_scope=self.flag_scope,
            scoped_flag_path=self.scope_flag_path,
            clear_scoped_pause=lambda selected: self.clear_pause(
                preserve_running_state=True, scope=selected
            ),
            clear_challenge=self.clear_challenge,
            set_pause=self.set_pause,
            remember_completion=self.remember_completion,
            logger=self.logger(),
        )

    def _clear_solver_manual_required_state(self) -> None:
        with self.runtime().lock:
            self.runtime().solver.clear_manual()
            self.runtime().recovery.clear_manual()

    def _clear_solver_running_state(self) -> None:
        self.runtime().solver.clear(finished_at=self.clock())

    def _request_solver_cancel(self) -> None:
        with self.runtime().lock:
            self.runtime().recovery.cancel(self.clock())
            self.runtime().solver.cancel()

    def _clear_solver_manual_required_pause(
        self, *, preserve_running_state: bool = False, scope: str | None = None
    ) -> str | None:
        from .solver_pause_cleanup import clear_manual_pause

        return clear_manual_pause(
            runtime=self.runtime(),
            scope=self.normalize_scope(scope) or None,
            preserve_running_state=preserve_running_state,
            flag_path=self.flag_path(),
            flag_scope=self.flag_scope(),
            scoped_flag_path=self.scope_flag_path,
            read_scope=self.read_scope,
            read_legacy=self.read_legacy,
            clear_challenge=self.clear_challenge,
            set_pause=self.set_pause,
            clear_running=self.clear_running,
            clear_manual=self.clear_manual,
        )

    def _clear_solver_manual_required_pause_compat(
        self, scope: str | None = None
    ) -> str | None:
        """Call the scoped cleanup while tolerating legacy test/plugin overrides."""
        try:
            return self.clear_pause(scope=scope)
        except TypeError as error:
            if "unexpected keyword" not in str(error):
                raise
            return self.clear_pause()

    def _mark_solver_manual_required(
        self, *, manual_only: bool = False, scope: str | None = None
    ) -> str | None:
        from .solver_manual_pause import mark_manual_required

        return mark_manual_required(
            runtime=self.runtime(),
            scope=self.normalize_scope(scope) or None,
            manual_only=manual_only,
            clock=self.clock,
            cancel=self.cancel,
            persist_scope=self.persist_scope,
            set_pause=self.set_pause,
            write_flag=self.write_flag,
        )

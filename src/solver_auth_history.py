"""Challenge identity and same-source authentication report grace policies."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, cast

from .collection_control_state import CHALLENGE_SCOPES
from .project_environment import EnvironmentAliasConflict
from .project_environment import getenv as project_getenv

if TYPE_CHECKING:
    from .runtime_state import RuntimeState


@dataclass(frozen=True)
class SolverAuthHistory:
    runtime: Callable[[], RuntimeState]
    clock: Callable[[], float]
    data_dir: Callable[[], str]
    state_path: Callable[[], Path]
    normalize_target: Callable[[object], str]
    request_key: Callable[[object], tuple[str, str, str]]
    build_request: Callable[[object], dict[str, str]]
    captured_count: Callable[[], int | None]
    infer_scope: Callable[[object], str | None]
    normalize_scope: Callable[[object], str | None]
    matches_source: Callable[[object, object], bool]
    reset_grace: Callable[[], float]
    auth_grace: Callable[[], float]
    progress_grace: Callable[[], float]
    progress_min_items: Callable[[], int]
    same_target: Callable[[str, str, str], bool]
    suppression: Callable[..., dict[str, object] | None]

    __all__: ClassVar[tuple[str, ...]] = (
        "_solver_challenge_state_path",
        "_read_solver_challenge_state",
        "_solver_challenge_request_key",
        "_solver_challenge_owner_key",
        "_remember_solver_auth_completion",
        "_solver_request_matches_auth_source",
        "_remember_solver_force_reset_recovery",
        "_solver_force_reset_report_suppression",
        "_solver_auth_report_suppression",
        "_solver_report_is_recent_auth_duplicate",
    )

    def _solver_challenge_state_path(self) -> Path:
        state_dir = (
            str(project_getenv("CROW_SOLVER_STATE_DIR") or self.data_dir()).strip()
            or self.data_dir()
        )
        return Path(state_dir) / "solver-challenge-state.json"

    def _read_solver_challenge_state(self) -> dict[str, object]:
        try:
            payload = json.loads(self.state_path().read_text(encoding="utf-8"))
        except EnvironmentAliasConflict:
            raise
        except Exception:  # noqa: BLE001 - unreadable legacy receipts are absent
            return {}
        if not isinstance(payload, dict) or payload.get("active") is not True:
            return {}
        challenge_id = str(payload.get("challenge_id") or "").strip()
        if not challenge_id:
            return {}
        last_request = payload.get("last_request")
        payload["challenge_id"] = challenge_id
        payload["last_request"] = (
            dict(last_request) if isinstance(last_request, dict) else {}
        )
        return payload

    def _solver_challenge_request_key(
        self, request_payload: dict[str, object] | None
    ) -> tuple[str, str, str]:
        payload = request_payload if isinstance(request_payload, dict) else {}
        node_id = str(payload.get("node_id") or "").strip().lower()
        cdp_endpoint = (
            str(payload.get("cdp_endpoint") or "").strip().lower().rstrip("/")
        )
        target_url = self.normalize_target(
            payload.get("challenge_target_url")
            or payload.get("target_url")
            or payload.get("url")
            or ""
        )
        return node_id, cdp_endpoint, target_url

    def _solver_challenge_owner_key(
        self, request_payload: dict[str, object] | None
    ) -> tuple[str, str]:
        node_id, cdp_endpoint, _target_url = self.request_key(request_payload)
        return node_id, cdp_endpoint

    def _remember_solver_auth_completion(
        self, request_payload: dict[str, object] | None
    ) -> None:
        request = self.build_request(request_payload or {})
        completed_at = self.clock()
        captured_count = self.captured_count()
        self.runtime().recovery.record_auth_completion(
            completed_at, request, captured_count
        )

    def _solver_request_matches_auth_source(
        self,
        completed_request: dict[str, object],
        incoming_request: dict[str, object],
    ) -> bool:
        completed_scope = self.infer_scope(completed_request)
        incoming_scope = self.infer_scope(incoming_request)
        # Legacy unscoped recovery only proved detail progress, never list access.
        if incoming_scope == "seed" and completed_scope != "seed":
            return False
        if completed_scope and incoming_scope and completed_scope != incoming_scope:
            return False
        completed_node, completed_cdp, completed_target = self.request_key(
            completed_request
        )
        incoming_node, incoming_cdp, incoming_target = self.request_key(
            incoming_request
        )
        if completed_node and incoming_node:
            return completed_node == incoming_node
        if completed_cdp and incoming_cdp:
            return completed_cdp == incoming_cdp
        return bool(
            completed_target and incoming_target and completed_target == incoming_target
        )

    def _remember_solver_force_reset_recovery(
        self,
        scope: str,
        request_payload: dict[str, object] | None,
        *,
        now: float | None = None,
    ) -> None:
        """Remember a scoped reset so its just-closed page cannot immediately re-lock collection."""
        normalized_scope = self.normalize_scope(scope)
        request = self.build_request(request_payload or {})
        if normalized_scope not in CHALLENGE_SCOPES or not request:
            return
        self.runtime().control.remember_force_reset(
            normalized_scope,
            self.clock() if now is None else float(now),
            request,
        )

    def _solver_force_reset_report_suppression(
        self,
        request_payload: dict[str, object] | None,
        *,
        now: float | None = None,
    ) -> dict[str, object] | None:
        """Ignore same-scope reports briefly after a forced recovery attempt."""
        incoming = self.build_request(request_payload or {})
        scope = self.infer_scope(incoming)
        if scope not in CHALLENGE_SCOPES or self.reset_grace() <= 0:
            return None
        recovery = self.runtime().control.force_reset_snapshot(scope)
        completed_at = float(
            cast("str | float", recovery.get("completed_at_epoch") or 0)
        )
        completed_request = self.build_request(recovery.get("request") or {})
        if completed_at <= 0 or not completed_request or not incoming:
            return None
        current_time = self.clock() if now is None else float(now)
        age = current_time - completed_at
        if age < 0 or age > self.reset_grace():
            return None
        if not self.matches_source(completed_request, incoming):
            return None
        return {
            "reason": "recent_force_reset",
            "scope": scope,
            "age_seconds": age,
            "grace_seconds": self.reset_grace(),
        }

    def _solver_auth_report_suppression(
        self,
        request_payload: dict[str, object] | None,
        *,
        now: float | None = None,
    ) -> dict[str, object] | None:
        recovery = self.runtime().recovery.snapshot()
        completed_at = recovery.completed_at
        if completed_at <= 0:
            return None
        current_time = self.clock() if now is None else float(now)
        age = current_time - completed_at
        max_grace_seconds = max(
            self.auth_grace(),
            self.progress_grace(),
        )
        if age < 0 or age > max_grace_seconds:
            return None

        completed = self.build_request(recovery.completed_request)
        incoming = self.build_request(request_payload or {})
        if not completed or not incoming:
            return None
        if not self.matches_source(completed, incoming):
            return None

        incoming_scope = self.infer_scope(incoming)
        if incoming_scope == "seed" and not self.same_target(
            "seed", self.request_key(completed)[2], self.request_key(incoming)[2]
        ):
            return None
        if self.auth_grace() > 0 and age <= self.auth_grace():
            return {
                "reason": "recent_auth_complete",
                "age_seconds": age,
                "grace_seconds": self.auth_grace(),
                "captured_since_auth": 0,
            }

        if incoming_scope != "detail":
            return None
        baseline = recovery.completed_detail_count
        current_count = self.captured_count()
        if baseline is None or current_count is None:
            return None
        captured_since_auth = max(current_count - baseline, 0)
        if (
            age > self.progress_grace()
            or captured_since_auth < self.progress_min_items()
        ):
            return None
        return {
            "reason": "recent_detail_progress",
            "age_seconds": age,
            "grace_seconds": self.progress_grace(),
            "captured_since_auth": captured_since_auth,
        }

    def _solver_report_is_recent_auth_duplicate(
        self,
        request_payload: dict[str, object] | None,
        *,
        now: float | None = None,
    ) -> bool:
        """Reject delayed captcha reports from the node that just completed auth.

        Worker captcha reports are fire-and-forget and do not carry the active
        challenge id.  A report already in flight can therefore arrive after the
        solver has cleared the challenge and otherwise create a new pause.  Keep a
        short, same-stage grace window so the next worker cycle can observe the
        authenticated cookie. Seed reports also require the verified list target.
        Detail capture advances extend protection only for detail reports.
        """
        return self.suppression(request_payload, now=now) is not None

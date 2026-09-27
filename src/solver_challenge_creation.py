"""Challenge creation/reuse policy with injected request and persistence owners."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from .collection_control_state import CHALLENGE_SCOPES

if TYPE_CHECKING:
    from .runtime_state import RuntimeState
    from .solver_pause_cleanup import PauseSetter


@dataclass(frozen=True)
class ChallengeCreation:
    runtime: RuntimeState
    build_request: Callable[[object], dict[str, str]]
    request_scope: Callable[[dict[str, str]], str | None]
    bind_root: Callable[[], object]
    read_scope: Callable[[str], Mapping[str, object]]
    read_legacy: Callable[[], Mapping[str, object]]
    persist_scope: Callable[[str, Mapping[str, object]], str | None]
    persist_legacy: Callable[[str, dict[str, str]], str | None]
    owner_key: Callable[[object], tuple[str, str]]
    request_key: Callable[[object], tuple[str, str, str]]
    effectively_paused: Callable[[], bool]
    set_pause: PauseSetter
    clock: Callable[[], float]
    new_id: Callable[[], str]
    logger: logging.Logger

    def begin_locked(self, request_payload: object) -> str:
        """Caller holds runtime.lock across reads, publication and cache updates."""
        supplied = (
            request_payload
            if isinstance(request_payload, dict)
            else self.runtime.recovery.snapshot().last_request
        )
        request = self.build_request(supplied or {})
        # Only explicit scoped requests opt into independent challenge ownership.
        scope = self.request_scope(request) if isinstance(request_payload, dict) else ""
        if scope in CHALLENGE_SCOPES:
            return self._begin_scoped(cast("str", scope), request)
        return self._begin_legacy()

    def _begin_scoped(self, scope: str, request: dict[str, str]) -> str:
        now = self.clock()
        self.bind_root()
        state = self.runtime.control.scope_snapshot(scope)
        persisted = self.read_scope(scope)
        if not state.get("challenge_id") and persisted.get("challenge_id"):
            state.update(persisted)
        challenge_id = str(state.get("challenge_id") or "").strip() or self.new_id()
        first_seen = (
            float(cast("str | float", state.get("first_seen_epoch") or 0)) or now
        )
        state.update(
            challenge_id=challenge_id,
            last_request=dict(request),
            first_seen_epoch=first_seen,
            pause_started_epoch=float(
                cast("str | float", state.get("pause_started_epoch") or 0)
            )
            or now,
            paused=True,
            pause_reason="captcha_solver",
            manual_required=False,
            manual_only=False,
            last_status="running",
            last_failure_reason=None,
        )
        error = self.persist_scope(scope, state)
        if error:
            self.logger.error(
                "[SOLVER] Failed to persist %s challenge state: %s", scope, error
            )
        # The scoped latch remains authoritative; publish its compatibility mirror next.
        legacy_error = self.persist_legacy(challenge_id, request)
        if legacy_error:
            self.logger.error(
                "[SOLVER] Failed to refresh legacy challenge state: %s", legacy_error
            )
        self.set_pause(True, "captcha_solver", scope=scope)
        self.runtime.recovery.set_challenge(challenge_id, request)
        return challenge_id

    def _begin_legacy(self) -> str:
        request = dict(self.runtime.recovery.snapshot().last_request)
        persisted = self.read_legacy()
        if (
            self.runtime.recovery.snapshot().challenge_id
            and self.effectively_paused()
            and (
                not persisted
                or self.owner_key(persisted.get("last_request"))
                == self.owner_key(request)
            )
        ):
            challenge_id = cast("str", self.runtime.recovery.snapshot().challenge_id)
            error = self.persist_legacy(challenge_id, request)
            if error:
                self.logger.error(
                    "[SOLVER] Failed to refresh persisted challenge state: %s", error
                )
            return cast("str", self.runtime.recovery.snapshot().challenge_id)
        if persisted and self.request_key(
            persisted.get("last_request")
        ) == self.request_key(request):
            self.runtime.recovery.set_challenge(cast("str", persisted["challenge_id"]))
        else:
            self.runtime.recovery.set_challenge(self.new_id())
        error = self.persist_legacy(
            cast("str", self.runtime.recovery.snapshot().challenge_id), request
        )
        if error:
            self.logger.error("[SOLVER] Failed to persist challenge state: %s", error)
        return cast("str", self.runtime.recovery.snapshot().challenge_id)

"""Native receipt boundary for authentication completion and replay protection."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from . import auth_completion_store
from .auth_cleanup_journal import completion_is_pending
from .runtime_state import RuntimeState
from .solver_recovery_state import SolverRecoveryState


@dataclass(frozen=True)
class AuthCompletionReceipts:
    runtime: Callable[[], RuntimeState]
    data_dir: Callable[[], str]
    env: Callable[[str], str | None]
    path: Callable[[], Path]
    recovery: Callable[[], SolverRecoveryState]
    scope_root: Callable[[], Path]
    clock: Callable[[], float]

    __all__: ClassVar[list[str]] = [
        "_normalize_auth_completion_id",
        "_auth_completion_confirmation_path",
        "_read_auth_completion_confirmations",
        "_auth_completion_recovery_state",
        "_auth_completion_was_confirmed",
        "_remember_auth_completion_confirmation",
    ]

    def _normalize_auth_completion_id(self, value: object) -> str | None:
        return auth_completion_store.normalize_completion_id(value)

    def _auth_completion_confirmation_path(self) -> Path:
        state_dir = str(self.env("FAPAI_SOLVER_STATE_DIR") or self.data_dir()).strip()
        return Path(state_dir or self.data_dir()) / "auth-completion-confirmations.json"

    def _read_auth_completion_confirmations(self) -> dict[str, float]:
        return auth_completion_store.read_confirmations(self.path())

    def _auth_completion_recovery_state(self) -> SolverRecoveryState:
        return self.runtime().recovery

    def _auth_completion_was_confirmed(self, completion_id: str | None) -> bool:
        if not completion_id:
            return False
        with self.runtime().lock:
            if completion_is_pending(self.scope_root(), completion_id):
                return False
            return auth_completion_store.was_confirmed(
                completion_id, path=self.path(), state=self.recovery()
            )

    def _remember_auth_completion_confirmation(
        self, completion_id: str | None
    ) -> str | None:
        if not completion_id:
            return None
        return auth_completion_store.remember_confirmation(
            completion_id, path=self.path(), state=self.recovery(), clock=self.clock
        )

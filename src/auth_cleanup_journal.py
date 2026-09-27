"""Write-ahead challenges keep interrupted auth cleanup retryable."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from .archive_json_io import write_json
from .auth_completion_store import normalize_completion_id
from .collection_control_state import CHALLENGE_SCOPES, new_scope_state

_INTENT_SCOPES = (*CHALLENGE_SCOPES, "legacy")

_PROTECTED_INTENTS: ContextVar[frozenset[Path]] = ContextVar(
    "auth_cleanup_protected_intents", default=frozenset()
)


def _path(directory: Path, scope: str) -> Path:
    if scope not in _INTENT_SCOPES:
        raise ValueError("Invalid auth cleanup scope")
    return directory / f"auth-cleanup-intent-{scope}.json"


def _state(payload: object, *, legacy: bool = False) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("Invalid auth cleanup state")  # noqa: TRY004 - invalid receipt schema
    result: dict[str, object] = dict(new_scope_state())
    if legacy:
        result.update(resume_epoch=0.0, required_epoch=0.0)
    for key, default in result.items():
        value = payload.get(key, default)
        if key == "last_request":
            valid = isinstance(value, dict) and all(
                isinstance(k, str) and isinstance(v, str) for k, v in value.items()
            )
        elif isinstance(default, bool):
            valid = isinstance(value, bool)
        elif isinstance(default, (int, float)):
            valid = (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                and value >= 0
            )
        else:
            valid = value is None or isinstance(value, str)
        if not valid:
            raise ValueError("Invalid auth cleanup state field")
        result[key] = value
    challenge_id = result["challenge_id"]
    if not isinstance(challenge_id, str) or not challenge_id.strip():
        raise ValueError("Missing auth cleanup challenge")
    return result


def _read(directory: Path, scope: str) -> tuple[str | None, dict[str, object]] | None:
    try:
        payload: object = json.loads(
            _path(directory, scope).read_text(encoding="utf-8")
        )
    except FileNotFoundError:
        return None
    if (
        not isinstance(payload, dict)
        or type(payload.get("version")) is not int
        or payload.get("version") != 1
        or payload.get("scope") != scope
    ):
        raise ValueError("Invalid auth cleanup intent")
    completion_id = payload.get("completion_id")
    if completion_id is not None and (
        not isinstance(completion_id, str)
        or not completion_id
        or normalize_completion_id(completion_id) != completion_id
    ):
        raise ValueError("Invalid auth cleanup completion ID")
    return completion_id, _state(payload.get("state"), legacy=scope == "legacy")


@dataclass(frozen=True)
class AuthCleanupIntent:
    directory: Path
    scope: str | None
    state: Mapping[str, object]
    completion_id: str | None

    @property
    def active(self) -> bool:
        return (self.scope is None or self.scope in CHALLENGE_SCOPES) and bool(
            self.state.get("challenge_id")
        )

    def prepare(
        self,
        *,
        read_scope: Callable[[str], Mapping[str, object]] | None = None,
    ) -> str | None:
        try:
            if self.scope not in CHALLENGE_SCOPES and read_scope is not None:
                for candidate in CHALLENGE_SCOPES:
                    if (
                        read_scope(candidate).get("challenge_id")
                        or _read(self.directory, candidate) is not None
                    ):
                        return (
                            "active scoped challenge requires scope-specific completion"
                        )
            if not self.active:
                return None
            scope = self.scope or "legacy"
            _read(self.directory, scope)
            state = _state(dict(self.state), legacy=scope == "legacy")
            self.directory.mkdir(parents=True, exist_ok=True)
            write_json(
                _path(self.directory, scope),
                {
                    "version": 1,
                    "scope": scope,
                    "state": state,
                    "completion_id": normalize_completion_id(self.completion_id),
                },
            )
        except (OSError, ValueError, TypeError) as error:
            return f"failed to prepare auth cleanup: {error!r}"
        return None

    @contextmanager
    def preserve_during_cleanup(self) -> Iterator[None]:
        paths = _PROTECTED_INTENTS.get()
        if self.active:
            paths = paths | {_path(self.directory, self.scope or "legacy")}
        token = _PROTECTED_INTENTS.set(paths)
        try:
            yield
        finally:
            _PROTECTED_INTENTS.reset(token)

    def finish(self) -> str | None:
        if not self.active:
            return None
        try:
            _path(self.directory, self.scope or "legacy").unlink()
        except OSError as error:
            return f"failed to finish auth cleanup: {error!r}"
        return None


def completion_is_pending(directory: Path, completion_id: str) -> bool:
    normalized = normalize_completion_id(completion_id)
    return any(
        record is not None and record[0] == normalized
        for scope in _INTENT_SCOPES
        for record in [_read(directory, scope)]
    )


def retire_unprotected_cleanups(
    directory: Path,
    scope: str | None,
    *,
    read_scope: Callable[[str], Mapping[str, object]] | None = None,
) -> str | None:
    """Explicit reset/resume must not resurrect an older incomplete transaction."""
    scopes = (scope,) if scope else _INTENT_SCOPES
    if scope and read_scope is not None and read_scope(scope).get("challenge_id"):
        # A later scoped publication supersedes legacy cleanup, even if reset next.
        scopes += ("legacy",)
    for candidate in scopes:
        path = _path(directory, candidate)
        if path in _PROTECTED_INTENTS.get():
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            return f"failed to retire auth cleanup: {error!r}"
    return None


def recover_pending_cleanups(
    directory: Path,
    *,
    read_scope: Callable[[str], Mapping[str, object]],
    persist_scope: Callable[[str, Mapping[str, object]], str | None],
    read_legacy: Callable[[], Mapping[str, object]] | None = None,
    restore_legacy: Callable[[Mapping[str, object]], str | None] | None = None,
) -> int:
    """Run before startup restores latches or starts workers; errors block startup."""
    recovered = 0
    for scope in CHALLENGE_SCOPES:
        record = _read(directory, scope)
        if record is None:
            continue
        _, state = record
        current = read_scope(scope)
        current_id = current.get("challenge_id")
        if current_id and current_id != state["challenge_id"]:
            # A later published challenge owns this scope; never resurrect its predecessor.
            _path(directory, scope).unlink()
            continue
        if current_id == state["challenge_id"] and current.get("paused") is True:
            # A still-active challenge may contain newer request ownership metadata.
            recovered += 1
            continue
        state["paused"] = True
        state["pause_reason"] = state.get("pause_reason") or "manual_required"
        error = persist_scope(scope, state)
        if error:
            raise OSError(f"Failed to recover pending auth cleanup: {error}")
        # Keep the intent until a retry commits, even if its receipt was written.
        recovered += 1
    record = _read(directory, "legacy")
    if record is None:
        return recovered
    if read_legacy is None or restore_legacy is None:
        raise ValueError("Legacy auth cleanup recovery is not configured")
    _, state = record
    current = read_legacy()
    newer_scoped = any(
        read_scope(scope).get("challenge_id") or _read(directory, scope) is not None
        for scope in CHALLENGE_SCOPES
    )
    if newer_scoped or (
        current.get("challenge_id") and current["challenge_id"] != state["challenge_id"]
    ):
        _path(directory, "legacy").unlink()
        return recovered
    if current.get("challenge_id") == state["challenge_id"]:
        state["last_request"] = current.get("last_request", state["last_request"])
        state = _state(state, legacy=True)
    error = restore_legacy(state)
    if error:
        raise OSError(f"Failed to recover pending legacy auth cleanup: {error}")
    return recovered + 1

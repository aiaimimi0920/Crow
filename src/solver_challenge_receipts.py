"""Challenge receipt publication and cleanup with explicit runtime ownership."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, cast

from .collection_control_state import CHALLENGE_SCOPES, new_scope_state

if TYPE_CHECKING:
    from .runtime_state import RuntimeState


def persist_legacy_challenge(
    challenge_id: str,
    last_request: Mapping[str, object],
    *,
    path: Path,
    read_legacy: Callable[[], Mapping[str, object]],
    clock: Callable[[], float],
) -> str | None:
    from .archive_json_io import write_json

    existing = read_legacy()
    created_at_epoch = clock()
    if existing.get("challenge_id") == challenge_id:
        created_at_epoch = (
            float(cast("str | float", existing.get("created_at_epoch") or 0))
            or created_at_epoch
        )
    payload = {
        "active": True,
        "challenge_id": challenge_id,
        "created_at_epoch": created_at_epoch,
        "updated_at_epoch": clock(),
        "pause_reason": "captcha_solver",
        "last_request": dict(last_request),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, payload, indent=2)
    except Exception as error:  # noqa: BLE001 - preserve receipt error contract
        return repr(error)
    return None


def retire_and_clear(
    *,
    runtime: RuntimeState,
    directory: Callable[[], Path],
    scope: str | None,
    read_scope: Callable[[str], Mapping[str, object]],
    clear_locked: Callable[[], str | None],
) -> str | None:
    from .auth_cleanup_journal import retire_unprotected_cleanups

    with runtime.lock:
        error = cast(
            "str | None",
            retire_unprotected_cleanups(directory(), scope, read_scope=read_scope),
        )
        if error:
            return error
        return clear_locked()


def clear_challenges_locked(
    *,
    runtime: RuntimeState,
    scope: str | None,
    legacy_path: Callable[[], Path],
    scoped_path: Callable[[str], Path],
    read_legacy: Callable[[], Mapping[str, object]],
    read_scope: Callable[[str], Mapping[str, object]],
) -> str | None:
    """Caller holds runtime.lock, including retirement of unprotected intents."""
    scopes = (scope,) if scope else CHALLENGE_SCOPES
    errors: list[str] = []
    legacy_payload = read_legacy() if scope else {}
    scoped_id = str(read_scope(scope).get("challenge_id") or "") if scope else ""
    if scope and scoped_id and legacy_payload.get("challenge_id") == scoped_id:
        # Keep the authoritative scoped latch until compatibility cleanup succeeds.
        try:
            legacy_path().unlink(missing_ok=True)
        except Exception as error:  # noqa: BLE001 - preserve receipt error contract
            return f"legacy: {error!r}"
    for candidate in scopes:
        try:
            scoped_path(candidate).unlink(missing_ok=True)
        except Exception as error:  # noqa: BLE001 - preserve receipt error contract
            errors.append(f"{candidate}: {error!r}")
        else:
            runtime.control.set_scope(candidate, new_scope_state())
    if scope and errors:
        return "; ".join(errors)
    if not scope:
        try:
            legacy_path().unlink(missing_ok=True)
        except Exception as error:  # noqa: BLE001 - preserve receipt error contract
            errors.append(f"legacy: {error!r}")
        else:
            runtime.recovery.set_challenge(None)
    elif (
        str(runtime.recovery.snapshot().challenge_id or "").strip()
        and runtime.recovery.snapshot().challenge_id == scoped_id
    ):
        runtime.recovery.set_challenge(None)
        for other_scope in CHALLENGE_SCOPES:
            if other_scope == scope:
                continue
            other_state = read_scope(other_scope)
            if other_state.get("challenge_id"):
                runtime.recovery.set_challenge(
                    str(other_state.get("challenge_id")),
                    dict(
                        cast("Mapping[str, str]", other_state.get("last_request") or {})
                    ),
                )
                break
    return "; ".join(errors) if errors else None

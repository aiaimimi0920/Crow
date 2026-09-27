"""Legacy manual-flag reading and scoped retry eligibility."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, cast

from .collection_control_state import CHALLENGE_SCOPES

if TYPE_CHECKING:
    from .runtime_state import RuntimeState


def _read_flag(path: Callable[[], str]) -> dict[str, object] | None:
    try:
        with open(path(), "r", encoding="utf-8") as flag_file:
            payload = json.load(flag_file)
    except Exception:  # noqa: BLE001 - retain opaque/unreadable legacy flag fallback
        return None
    return payload if isinstance(payload, dict) else None


def manual_flag_scope(
    path: Callable[[], str], normalize: Callable[[object], str | None]
) -> str | None:
    payload = _read_flag(path)
    return (normalize(payload.get("scope")) or None) if payload is not None else None


def manual_flag_is_manual_only(path: Callable[[], str]) -> bool:
    value = (_read_flag(path) or {}).get("manual_only")
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def manual_flag_request(path: str) -> dict[str, object]:
    request = (_read_flag(lambda: path) or {}).get("last_request")
    return dict(request) if isinstance(request, dict) else {}


def manual_retry_enabled(
    *,
    runtime: RuntimeState,
    scope: str | None,
    infer_scope: Callable[[dict[str, str]], str | None],
    scope_status: Callable[[str], Mapping[str, object]],
    flag_scope: Callable[[], str | None],
    flag_manual_only: Callable[[], bool],
    configured_enabled: Callable[[], bool],
) -> bool:
    if scope not in CHALLENGE_SCOPES:
        inferred = infer_scope(runtime.recovery.snapshot().last_request)
        if inferred in CHALLENGE_SCOPES:
            scope = inferred
    if scope in CHALLENGE_SCOPES:
        scoped = scope_status(cast("str", scope))
        if scoped.get("manual_only"):
            return False
        owner = flag_scope()
        if owner and owner != scope:
            return True
        if scoped.get("challenge_id") or scoped.get("manual_required"):
            # Another scope's compatibility bit must not disable this scope's retry.
            return configured_enabled()
    if runtime.recovery.snapshot().manual_only or flag_manual_only():
        return False
    return configured_enabled()

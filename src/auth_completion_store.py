"""Durable authentication confirmation receipts with explicit state ownership."""

import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, cast

from src.archive_json_io import write_json

if TYPE_CHECKING:
    from src.solver_recovery_state import SolverRecoveryState


def normalize_completion_id(value: object) -> str | None:
    completion_id = str(value or "").strip()
    return completion_id[:160] if completion_id else None


def read_confirmations(path: Path) -> dict[str, float]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    raw = payload.get("confirmations") if isinstance(payload, dict) else None
    if not isinstance(raw, dict):
        # The file is readable JSON, but its serialized schema is invalid.
        raise ValueError("Invalid authentication confirmation receipt")  # noqa: TRY004
    confirmations: dict[str, float] = {}
    for raw_id, raw_epoch in raw.items():
        completion_id = normalize_completion_id(raw_id)
        if not completion_id or completion_id in confirmations:
            raise ValueError("Invalid or duplicate authentication confirmation ID")
        try:
            epoch = float(raw_epoch)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError("Invalid authentication confirmation timestamp") from error
        if isinstance(raw_epoch, bool) or not math.isfinite(epoch) or epoch < 0:
            raise ValueError("Invalid authentication confirmation timestamp")
        confirmations[completion_id] = epoch
    return confirmations


def was_confirmed(
    completion_id: str | None, *, path: Path, state: "SolverRecoveryState"
) -> bool:
    if not completion_id:
        return False
    with state.lock:
        confirmations = state.confirmation_snapshot()
        confirmations.update(read_confirmations(path))
        state.replace_confirmations(confirmations)
        return cast("bool", state.was_confirmation_recorded(completion_id))


def remember_confirmation(
    completion_id: str | None,
    *,
    path: Path,
    state: "SolverRecoveryState",
    clock: Callable[[], float],
) -> str | None:
    if not completion_id:
        return None
    with state.lock:
        try:
            confirmations = read_confirmations(path)
        except (OSError, ValueError) as error:
            return repr(error)
        confirmations.update(state.confirmation_snapshot())
        confirmations[completion_id] = clock()
        if len(confirmations) > 256:
            confirmations = dict(
                sorted(confirmations.items(), key=lambda item: item[1])[-192:]
            )
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            write_json(path, {"confirmations": confirmations}, indent=2)
        except Exception as error:  # noqa: BLE001 - public API returns publication errors.
            return repr(error)
        state.replace_confirmations(confirmations)
    return None

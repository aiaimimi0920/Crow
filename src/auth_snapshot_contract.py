"""Shared recovery errors and immutable manual snapshot naming, without I/O."""

import re
from os import PathLike
from pathlib import Path


class RecoveryError(RuntimeError):
    pass


def snapshot_path(base: str | PathLike[str], recovery_id: str, digest: str) -> Path:
    if not re.fullmatch(r"auth-recovery-[a-f0-9]{32}", recovery_id):
        raise RecoveryError("invalid_request")
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise RecoveryError("invalid_snapshot")
    return Path(base).parent / "desktop-auth" / f"{recovery_id}-{digest}.json"

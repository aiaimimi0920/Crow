"""Fail-closed authentication demand from the inspected worker controller lease."""

import math
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from .collection_engine_restart import runtime_root


def collection_workers_available(*, root=None, now=None):
    """The controller renews this lease only after inspecting running workers.

    A solver heartbeat or configured worker count is not collection evidence.
    Read only: an absent control database must not be created by the auth API.
    """
    current = time.time() if now is None else float(now)
    path = (
        (runtime_root() if root is None else Path(root))
        / "control"
        / "pc2-engine-restart.sqlite3"
    )
    try:
        with closing(
            sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)
        ) as db:
            row = db.execute("SELECT heartbeat FROM controller WHERE id=1").fetchone()
        seen = float(row[0]) if row else float("nan")
        return (
            math.isfinite(current) and math.isfinite(seen) and 0 <= current - seen <= 30
        )
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return False

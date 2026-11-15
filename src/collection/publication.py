"""Serialize cooperating DB/JSON publishers; never acknowledge a failed archive.

The archive lock spans commit, canonical read and publication. Database-only
writers must arrange their own publication; this is not a distributed transaction.
"""

from collections.abc import Callable
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any

from src import archive_json_io
from src.archive_transaction import archive_transaction


def publish_record(
    path: str,
    item_id: str,
    record: dict[str, Any],
    event_type: str,
    payload: dict[str, Any] | None,
    *,
    persist: Callable[..., dict[str, Any] | None],
    publish: Callable[..., dict[str, Any] | None],
    seed: bool = False,
) -> dict[str, Any]:
    with archive_transaction(path):
        if pending_marker(path, item_id).exists():
            raise RuntimeError(
                "Detail publication awaits database recovery; seed archive write blocked"
            )
        committed = persist(record, event_type, payload)
        if isinstance(committed, dict):
            # Use the DB result, not the pre-merge runtime snapshot.
            result = publish(path, item_id, committed)
            return deepcopy(result if isinstance(result, dict) else committed)
        # DB-disabled and legacy callback implementations keep their contract.
        result = (
            publish(path, item_id, record, merge=True)
            if seed
            else publish(path, item_id, record)
        )
        return deepcopy(result if isinstance(result, dict) else record)


def pending_marker(path: str, item_id: str) -> Path:
    suffix = sha256(str(item_id).encode("utf-8")).hexdigest()
    return Path(str(path) + ".pending-db-" + suffix)


@contextmanager
def detail_publication(path: str, item_id: str):
    """Keep JSON evidence protected if the following DB write fails or crashes.

    A successful retry clears the marker. Do not treat it as permission to replay
    an unknown DB operation. Seed writes fail closed until detail recovery.
    """
    with archive_transaction(path):
        marker = pending_marker(path, item_id)
        if not marker.exists():
            archive_json_io.write_json(
                marker, {"item_id": str(item_id), "stage": "detail_database_pending"}
            )
        yield
        marker.unlink()

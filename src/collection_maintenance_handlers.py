"""Collection maintenance routes shared with the legacy API facade."""

from typing import Protocol


class MaintenanceHandler(Protocol):
    def _submit_maintenance_job(self, kind: str, error_code: str) -> object: ...


__all__ = [
    "_post_detail_maintenance",
    "_post_fetch_missing_detail_archives",
    "_post_archive_detail_replay",
]


def _post_detail_maintenance(self: MaintenanceHandler) -> None:
    self._submit_maintenance_job(
        "recent_enrich_maintenance", "AVM_RECENT_ENRICH_MAINTENANCE_FAILED"
    )


def _post_fetch_missing_detail_archives(self: MaintenanceHandler) -> None:
    self._submit_maintenance_job(
        "fetch_missing_detail_archives", "AVM_FETCH_MISSING_DETAIL_ARCHIVES_FAILED"
    )


def _post_archive_detail_replay(self: MaintenanceHandler) -> None:
    self._submit_maintenance_job(
        "archive_detail_replay", "AVM_ARCHIVE_DETAIL_REPLAY_FAILED"
    )

"""Prepare source-neutral maintenance work before handing it to the API queue."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from src.archive_json_io import write_json
from src.collection_job_control import job_checkpoint
from src.collection_jobs import JobResult, JobWork
from src.collection_maintenance_options import nonnegative_integer


class MaintenanceService(Protocol):
    def fetch_missing_archives(self, **options: object) -> JobResult: ...

    def prepare_replay(self, **options: object) -> JobResult: ...

    def run_maintenance(self, **options: object) -> JobResult: ...


def prepare_maintenance(
    operation: str,
    payload: JobResult,
    data_root: Path,
    service: MaintenanceService,
    reload_data: Callable[[Path], object],
) -> JobWork:
    dry_run = payload.get("dry_run", True) is not False
    options: JobResult = {"dry_run": dry_run}
    if operation == "fetch_missing_detail_archives":
        runner = service.fetch_missing_archives
        options.update(
            limit=nonnegative_integer(payload.get("limit"), 20, negative=0),
            timeout=nonnegative_integer(payload.get("timeout"), 15) or 15,
            extract_risk=bool(payload.get("extract_risk", False)),
        )
        reload_key = "fetched_count"
    elif operation in {"archive_detail_replay", "recent_detail_replay"}:
        runner = service.prepare_replay
        recent = operation == "recent_detail_replay"
        options.update(
            window_days=nonnegative_integer(
                payload.get("window_days"), 7 if recent else 30
            ),
            limit=nonnegative_integer(
                payload.get("limit"), 100 if recent else 500, negative=0
            ),
        )
        reload_key = "prepared_count"
    elif operation == "recent_enrich_maintenance":
        runner = service.run_maintenance
        for key, default in (
            ("window_days", 7),
            ("archive_limit", 200),
            ("sample_limit", 20),
            ("replay_limit", 100),
            ("fetch_limit", 20),
            ("fetch_timeout", 15),
            ("reconcile_limit", 200),
        ):
            options[key] = nonnegative_integer(payload.get(key), default)
        options["fetch_timeout"] = options["fetch_timeout"] or 15
        for key in ("extract_risk", "prepare_replay", "fetch_archives"):
            options[key] = bool(payload.get(key, False))
        reload_key = "detail_replay_preparation"
    else:
        raise ValueError("Unknown collection maintenance operation")

    def run() -> JobResult:
        job_checkpoint()
        result = runner(**options)
        job_checkpoint()
        report = data_root / "avm" / f"{operation}.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        write_json(report, result, indent=2)
        changed = result.get(reload_key)
        if isinstance(changed, dict):
            changed = changed.get("prepared_count")
        if not dry_run and changed:
            job_checkpoint()
            reload_data(data_root)
        return result

    return run

"""Read-only projection of retired manual-review jobs and collection receipts."""

from collections.abc import Iterable, Mapping
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.collection_jobs import ACTIVE, TERMINAL
from src.runtime_json import load_json_file


def persisted_receipts(data_root: Path) -> list[dict[str, Any]]:
    """Read the last durable state without creating a worker or replaying work."""
    root = data_root.resolve() / "runtime" / "collection-jobs"
    receipts = []
    for path in root.glob("*.json"):
        job_id = path.stem
        if len(job_id) != 32 or any(char not in "0123456789abcdef" for char in job_id):
            continue
        payload = load_json_file(path)
        if (
            not isinstance(payload, dict)
            or payload.get("job_id") != job_id
            or not isinstance(payload.get("status"), str)
            or payload["status"] not in ACTIVE | TERMINAL
        ):
            raise ValueError("Invalid collection job receipt")
        if payload.get("operation") == "manual_review_receipt":
            receipts.append(payload)
    return receipts


def _created_at(job: Mapping[str, Any]) -> tuple[datetime, str]:
    try:
        instant = datetime.fromisoformat(
            str(job.get("created_at") or "").replace("Z", "+00:00")
        )
        instant = (
            instant.replace(tzinfo=timezone.utc)
            if instant.tzinfo is None
            else instant.astimezone(timezone.utc)
        )
    except ValueError:
        instant = datetime.min.replace(tzinfo=timezone.utc)
    return instant, str(job.get("job_id") or "")


def merge_job_snapshot(
    legacy: Mapping[str, Any], collection_receipts: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    """Keep historical jobs readable; canonical collection receipts win by ID."""
    jobs = {}
    for source in legacy.get("jobs") or []:
        if not isinstance(source, dict) or not source.get("job_id"):
            continue
        job = deepcopy(source)
        if job.get("status") in ACTIVE:
            job["status"] = "interrupted"
            job["error"] = {
                "code": "MANUAL_REVIEW_LEGACY_JOB_INTERRUPTED",
                "message": "Legacy execution is unconfirmed; inspect outputs before retrying",
            }
        jobs[str(job["job_id"])] = job
    for source in collection_receipts:
        if source.get("operation") != "manual_review_receipt":
            continue
        job = deepcopy(dict(source))
        result = job.get("result")
        receipt = result.get("receipt") if isinstance(result, dict) else None
        if isinstance(receipt, dict):
            job["receipt_key"] = {
                "action": str(receipt.get("action") or ""),
                "ready_signal": str(receipt.get("ready_signal") or ""),
            }
        jobs[str(job["job_id"])] = job
    ordered = sorted(jobs.values(), key=_created_at)
    return {
        "jobs": ordered,
        "queue": [job["job_id"] for job in ordered if job.get("status") == "queued"],
        "running_job_id": next(
            (
                job["job_id"]
                for job in ordered
                if job.get("status") in {"running", "cancelling"}
            ),
            None,
        ),
    }

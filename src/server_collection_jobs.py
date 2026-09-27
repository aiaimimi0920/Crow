"""Authenticated job admission, polling and cancellation over HTTP."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from src.collection_jobs import (
    CollectionJobManager,
    JobNotOwned,
    JobQueueFull,
    JobWork,
)
from src.server_http_responses import JsonResponseHandler, _write_json_response
from src.server_request_guard import _read_json_body, _require_control_plane


class JobHost(Protocol):
    def collection_jobs(self, data_root: Path) -> CollectionJobManager: ...


class JobRequest(JsonResponseHandler, Protocol):
    server: JobHost

    def send_json(self, data: object) -> None: ...


def enqueue_job(
    handler: JobRequest,
    operation: str,
    work: JobWork,
    failure_code: str,
    *,
    data_root: Path,
    job_id: str | None = None,
    response_status: int = 202,
    response_extra: Mapping[str, object] | None = None,
) -> None:
    try:
        job = handler.server.collection_jobs(data_root).submit(
            operation, work, failure_code, job_id=job_id
        )
    except JobQueueFull:
        handler.send_error_json(
            status=503,
            code="COLLECTION_JOB_QUEUE_FULL",
            message="Collection operation queue is unavailable",
        )
        return
    except Exception as error:
        handler.send_error_json(
            status=503,
            code="COLLECTION_JOB_SUBMISSION_FAILED",
            message="Unable to persist collection job",
            details={"error": str(error)},
        )
        return
    response = {
        "status": "accepted",
        "job_id": job["job_id"],
        "job_status": job["status"],
        "status_url": "/api/collection/jobs?id=" + str(job["job_id"]),
        "cancel_url": "/api/collection/jobs/cancel",
    }
    if response_extra:
        response.update(response_extra)
    _write_json_response(handler, response_status, response)


def get_job(handler: JobRequest, job_id: str, *, data_root: Path) -> None:
    if not _require_control_plane(handler):
        return
    if re.fullmatch(r"[a-f0-9]{32}", job_id) is None:
        handler.send_error_json(
            status=400,
            code="COLLECTION_JOB_INVALID_ID",
            message="A valid collection job ID is required",
        )
        return
    try:
        job = handler.server.collection_jobs(data_root).get(job_id)
    except Exception as error:
        handler.send_error_json(
            status=503,
            code="COLLECTION_JOB_STATE_UNAVAILABLE",
            message="Collection job receipt is unavailable",
            details={"error": str(error)},
        )
        return
    if job is None:
        handler.send_error_json(
            status=404,
            code="COLLECTION_JOB_NOT_FOUND",
            message="Collection job was not found",
        )
        return
    handler.send_json(job)


def cancel_job(handler: JobRequest, *, data_root: Path) -> None:
    if not _require_control_plane(handler):
        return
    accepted, payload = _read_json_body(handler)
    if not accepted or payload is None:
        return
    job_id = payload.get("job_id")
    if not isinstance(job_id, str) or re.fullmatch(r"[a-f0-9]{32}", job_id) is None:
        handler.send_error_json(
            status=400,
            code="COLLECTION_JOB_INVALID_ID",
            message="A valid collection job ID is required",
        )
        return
    try:
        job = handler.server.collection_jobs(data_root).cancel(job_id)
    except JobNotOwned:
        handler.send_error_json(
            status=409,
            code="COLLECTION_JOB_NOT_OWNED",
            message="Execution is unconfirmed; inspect outputs before retrying",
        )
        return
    except Exception as error:
        handler.send_error_json(
            status=503,
            code="COLLECTION_JOB_STATE_UNAVAILABLE",
            message="Unable to persist collection job cancellation",
            details={"error": str(error)},
        )
        return
    if job is None:
        handler.send_error_json(
            status=404,
            code="COLLECTION_JOB_NOT_FOUND",
            message="Collection job was not found",
        )
        return
    handler.send_json(job)

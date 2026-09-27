"""Bounded background operations with durable receipts and no automatic replay."""

from __future__ import annotations

import copy
import json
import logging
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from src.archive_json_io import write_json
from src.collection_job_control import (
    DEFAULT_TIMEOUT_SECONDS,
    JobControl,
    JobStopped,
    job_scope,
    positive_timeout,
)
from src.runtime_json import load_json_file

logger = logging.getLogger(__name__)
JobResult = dict[str, object]
JobWork = Callable[[], JobResult]
ACTIVE = {"queued", "running", "cancelling"}
TERMINAL = {"completed", "failed", "cancelled", "timed_out", "interrupted"}


class JobQueueFull(RuntimeError):
    pass


class JobNotOwned(RuntimeError):
    pass


class CollectionJobFailure(RuntimeError):
    """A trusted operation stage supplies its public failure code."""

    def __init__(self, code: str) -> None:
        super().__init__("Collection operation failed")
        self.code = code


@dataclass(eq=False)
class PendingJob:
    receipt: JobResult
    work: JobWork
    failure_code: str
    control: JobControl
    timer: threading.Timer | None = None


class CollectionJobManager:
    """One daemon worker per API instance; only active work occupies memory."""

    def __init__(
        self,
        data_root: Path,
        *,
        capacity: int = 8,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if capacity < 1:
            raise ValueError("Job capacity must be positive")
        self.root = data_root.resolve() / "runtime" / "collection-jobs"
        self._capacity = capacity
        self._timeout = positive_timeout(timeout_seconds)
        self._owner_id = uuid4().hex
        self._lock = threading.Lock()
        self._pending: deque[PendingJob] = deque()
        self._active: dict[str, PendingJob] = {}
        self._thread: threading.Thread | None = None
        self._closed = False

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _path(self, job_id: str) -> Path:
        if re.fullmatch(r"[a-f0-9]{32}", job_id) is None:
            raise ValueError("Invalid collection job ID")
        return self.root / f"{job_id}.json"

    def _save(self, receipt: JobResult) -> None:
        write_json(self._path(str(receipt["job_id"])), receipt, indent=2)

    @staticmethod
    def _stop_error(job_id: str, reason: str) -> JobResult:
        return {
            "code": f"COLLECTION_JOB_{reason.upper()}",
            "message": "Operation stopped; inspect confirmed outputs before retrying",
            "error_id": job_id,
        }

    def _confirm_exit(self, entry: PendingJob, reason: str) -> None:
        receipt = dict(entry.receipt)
        receipt.update(
            status=reason,
            finished_at=self._now(),
            stop_reason=reason,
            error=self._stop_error(str(receipt["job_id"]), reason),
        )
        if (
            reason in {"cancelled", "timed_out"}
            and receipt["cancel_requested_at"] is None
        ):
            receipt["cancel_requested_at"] = self._now()
        try:
            self._save(receipt)
            entry.receipt = receipt
        except Exception:
            logger.exception(
                "Unable to confirm collection job exit: %s", receipt["job_id"]
            )

    def _request_stop(self, entry: PendingJob, reason: str) -> JobResult:
        if (
            entry.receipt["status"] in TERMINAL
            or entry.receipt["status"] == "cancelling"
        ):
            return copy.deepcopy(entry.receipt)
        job_id = str(entry.receipt["job_id"])
        reason = entry.control.stop_reason() or reason
        queued = entry.receipt["status"] == "queued"
        receipt = dict(entry.receipt)
        receipt.update(
            status=reason if queued else "cancelling",
            cancel_requested_at=self._now(),
            stop_reason=reason,
            error=self._stop_error(job_id, reason),
        )
        if queued:
            receipt["finished_at"] = self._now()
        # Persist before acknowledging cancellation or freeing the active slot.
        self._save(receipt)
        entry.receipt = receipt
        entry.control.request_stop(reason)
        if entry.timer is not None:
            entry.timer.cancel()
        if queued:
            if entry in self._pending:
                self._pending.remove(entry)
            self._active.pop(job_id, None)
        return copy.deepcopy(receipt)

    def _expire(self, job_id: str) -> None:
        try:
            with self._lock:
                entry = self._active.get(job_id)
                if entry is not None:
                    self._request_stop(entry, "timed_out")
        except Exception:
            logger.exception("Unable to persist collection job timeout: %s", job_id)

    def cancel(self, job_id: str) -> JobResult | None:
        with self._lock:
            entry = self._active.get(job_id)
            if entry is not None:
                return self._request_stop(entry, "cancelled")
            payload = self._load(job_id)
            if payload is not None and payload["status"] in ACTIVE:
                raise JobNotOwned("Collection job belongs to a previous API instance")
            return payload

    def _load(self, job_id: str) -> JobResult | None:
        try:
            payload = load_json_file(self._path(job_id))
        except FileNotFoundError:
            return None
        if (
            not isinstance(payload, dict)
            or payload.get("job_id") != job_id
            or not isinstance(payload.get("status"), str)
            or payload["status"] not in ACTIVE | TERMINAL
        ):
            raise ValueError("Invalid collection job receipt")
        return dict(payload)

    def submit(
        self,
        operation: str,
        work: JobWork,
        failure_code: str,
        *,
        job_id: str | None = None,
        timeout_seconds: float | None = None,
    ) -> JobResult:
        timeout = (
            self._timeout
            if timeout_seconds is None
            else positive_timeout(timeout_seconds)
        )
        with self._lock:
            if self._closed or len(self._active) >= self._capacity:
                raise JobQueueFull("Collection operation queue is unavailable")
            job_id = job_id or uuid4().hex
            if re.fullmatch(r"[a-f0-9]{32}", job_id) is None:
                raise ValueError("Invalid collection job ID")
            if self._path(job_id).exists():
                raise ValueError("Collection job ID already exists")
            control = JobControl(timeout)
            receipt: JobResult = {
                "job_id": job_id,
                "owner_id": self._owner_id,
                "operation": operation,
                "status": "queued",
                "created_at": self._now(),
                "deadline_at": (
                    datetime.now(timezone.utc) + timedelta(seconds=timeout)
                ).isoformat(),
                "timeout_seconds": timeout,
                "cancel_requested_at": None,
                "stop_reason": None,
                "started_at": None,
                "finished_at": None,
                "result": None,
                "error": None,
            }
            self.root.mkdir(parents=True, exist_ok=True)
            # Acknowledgement and work both require a durable queued receipt.
            self._save(receipt)
            entry = PendingJob(receipt, work, failure_code, control)
            entry.timer = threading.Timer(
                max(0.0, control.deadline - time.monotonic()),
                self._expire,
                args=(job_id,),
            )
            entry.timer.daemon = True
            self._pending.append(entry)
            self._active[job_id] = entry
            try:
                entry.timer.start()
                if self._thread is None:
                    thread = threading.Thread(
                        target=self._worker, name="collection-operations", daemon=True
                    )
                    self._thread = thread
                    try:
                        thread.start()
                    except BaseException:
                        self._thread = None
                        raise
            except BaseException:
                entry.timer.cancel()
                self._pending.remove(entry)
                self._active.pop(job_id, None)
                self._confirm_exit(entry, "interrupted")
                raise
            return copy.deepcopy(receipt)

    def get(self, job_id: str) -> JobResult | None:
        with self._lock:
            payload = self._load(job_id)
            if payload is None:
                return None
            if payload["status"] in ACTIVE and job_id not in self._active:
                # A restart never replays potentially completed writes.
                payload["status"] = "interrupted"
                payload["error"] = {
                    "code": "COLLECTION_JOB_INTERRUPTED",
                    "message": "Completion is unconfirmed; inspect outputs before retrying",
                    "error_id": job_id,
                }
            return dict(payload)

    def list(self, *, operation: str | None = None) -> list[JobResult]:
        """Return persisted receipts for compatibility/reporting endpoints.

        Completed receipts are intentionally read from disk instead of the
        in-memory queue so a restarted API can expose the same audit surface.
        ``queued``/``running`` receipts are projected as ``interrupted`` by
        :meth:`get` when this instance does not own them; no work is replayed.
        """
        with self._lock:
            paths = (
                sorted(self.root.glob("[a-f0-9][a-f0-9]*.json"))
                if self.root.exists()
                else []
            )
        receipts: list[JobResult] = []
        for path in paths:
            try:
                job_id = path.stem
                if re.fullmatch(r"[a-f0-9]{32}", job_id) is None:
                    continue
                payload = self.get(job_id)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if payload is None:
                continue
            if operation is not None and payload.get("operation") != operation:
                continue
            receipts.append(payload)
        return receipts

    def _worker(self) -> None:
        while True:
            with self._lock:
                if not self._pending:
                    self._thread = None
                    return
                entry = self._pending.popleft()
                job_id = str(entry.receipt["job_id"])
            try:
                self._execute(entry)
            except BaseException:
                self.close()
                with self._lock:
                    self._thread = None
                return
            finally:
                if entry.timer is not None:
                    entry.timer.cancel()
                with self._lock:
                    self._active.pop(job_id, None)

    def _execute(self, entry: PendingJob) -> None:
        try:
            with self._lock:
                if entry.receipt["status"] in TERMINAL:
                    return
                if self._closed:
                    self._request_stop(entry, "cancelled")
                    return
                entry.control.checkpoint()
                running = dict(entry.receipt, status="running", started_at=self._now())
                self._save(running)
                entry.receipt = running
            try:
                with job_scope(entry.control):
                    result = entry.work()
            except Exception as error:
                logger.exception("Collection job failed: %s", entry.receipt["job_id"])
                outcome: JobResult = {
                    "status": "failed",
                    "error": {
                        "code": error.code
                        if isinstance(error, CollectionJobFailure)
                        else entry.failure_code,
                        "message": "Collection operation failed",
                        "error_id": entry.receipt["job_id"],
                    },
                }
            else:
                outcome = {"status": "completed", "result": result}
            with self._lock:
                entry.control.checkpoint()
                receipt = dict(entry.receipt, **outcome, finished_at=self._now())
                self._save(receipt)
                entry.receipt = receipt
        except JobStopped as stopped:
            with self._lock:
                self._confirm_exit(entry, stopped.reason)
        except Exception:
            # Keep the last confirmed bytes and any failed temporary snapshot.
            logger.exception(
                "Collection job receipt unavailable: %s", entry.receipt["job_id"]
            )
        except BaseException:
            with self._lock:
                self._confirm_exit(entry, "interrupted")
            raise

    def close(self, timeout: float = 0) -> None:
        with self._lock:
            self._closed = True
            while self._pending:
                entry = self._pending.popleft()
                try:
                    self._request_stop(entry, "cancelled")
                except Exception:
                    logger.exception("Unable to confirm queued job cancellation")
                finally:
                    if entry.timer is not None:
                        entry.timer.cancel()
                    self._active.pop(str(entry.receipt["job_id"]), None)
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)

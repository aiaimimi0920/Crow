"""Durability, overload and restart contracts without application data."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from src import archive_json_io, collection_jobs
from src.collection_jobs import CollectionJobManager, JobQueueFull
from tools.test.collection_job_checks import wait_for_job


def completed(manager, receipt):
    return wait_for_job(manager.get, receipt["job_id"])


def test_bounded_fifo_queue_preserves_receipts_and_caller_isolation(tmp_path):
    manager = CollectionJobManager(tmp_path, capacity=2)
    entered, release = threading.Event(), threading.Event()
    calls = []

    def first():
        calls.append("first")
        entered.set()
        assert release.wait(5)
        return {"saved": ["original"]}

    try:
        a = manager.submit("first", first, "TEST_FAILED")
        assert entered.wait(2)
        b = manager.submit(
            "second", lambda: calls.append("second") or {}, "TEST_FAILED"
        )
        with pytest.raises(JobQueueFull):
            manager.submit("rejected", lambda: pytest.fail("overflow ran"), "FAILED")
        assert len(list(manager.root.glob("*.json"))) == 2
        a["status"] = "changed_by_caller"
        assert manager.get(a["job_id"])["status"] == "running"
        assert manager.get(b["job_id"])["status"] == "queued"
        release.set()
        assert completed(manager, a)["status"] == "completed"
        assert completed(manager, b)["status"] == "completed"
        assert calls == ["first", "second"]
        result = manager.get(a["job_id"])
        result["result"]["saved"].append("mutated")
        assert manager.get(a["job_id"])["result"] == {"saved": ["original"]}
        reopened = CollectionJobManager(tmp_path)
        assert reopened.get(a["job_id"])["status"] == "completed"
        assert calls == ["first", "second"]
    finally:
        release.set()
        manager.close(timeout=3)


def test_concurrent_admission_cannot_exceed_capacity(tmp_path):
    manager = CollectionJobManager(tmp_path, capacity=4)
    release = threading.Event()
    barrier = threading.Barrier(12)
    calls = []

    def work():
        assert release.wait(5)
        calls.append(True)
        return {}

    def submit():
        barrier.wait(timeout=3)
        try:
            return manager.submit("same", work, "TEST_FAILED")
        except JobQueueFull:
            return None

    try:
        with ThreadPoolExecutor(max_workers=12) as pool:
            receipts = list(pool.map(lambda _: submit(), range(12)))
        accepted = [receipt for receipt in receipts if receipt is not None]
        assert len(accepted) == 4
        release.set()
        for receipt in accepted:
            assert completed(manager, receipt)["status"] == "completed"
        assert len(calls) == 4
    finally:
        release.set()
        manager.close(timeout=3)


@pytest.mark.parametrize("status", ["queued", "running"])
def test_restart_reports_interrupted_work_without_replay_or_source_writes(
    tmp_path, status
):
    manager = CollectionJobManager(tmp_path)
    manager.root.mkdir(parents=True)
    job_id = "1" * 32
    path = manager.root / f"{job_id}.json"
    original = json.dumps(
        {"job_id": job_id, "status": status, "operation": "write"}
    ).encode()
    path.write_bytes(original)
    job = manager.get(job_id)
    assert job["status"] == "interrupted"
    assert job["error"]["code"] == "COLLECTION_JOB_INTERRUPTED"
    assert path.read_bytes() == original


def test_corrupt_receipt_is_preserved(tmp_path):
    manager = CollectionJobManager(tmp_path)
    manager.root.mkdir(parents=True)
    job_id = "2" * 32
    path = manager.root / f"{job_id}.json"
    path.write_bytes(b'{"broken":')
    with pytest.raises(ValueError):
        manager.get(job_id)
    assert path.read_bytes() == b'{"broken":'
    with pytest.raises(ValueError, match="job ID"):
        manager.get("../../outside")


def test_failed_admission_never_executes_work(tmp_path, monkeypatch):
    manager = CollectionJobManager(tmp_path)

    def fail(_descriptor):
        raise OSError("synthetic fsync failure")

    monkeypatch.setattr(archive_json_io.os, "fsync", fail)
    with pytest.raises(OSError, match="fsync"):
        manager.submit(
            "write", lambda: pytest.fail("unconfirmed job ran"), "TEST_FAILED"
        )
    assert list(manager.root.glob("*.json")) == []
    assert list(manager.root.glob("*.tmp"))


def test_failure_is_queryable_without_exception_text(tmp_path):
    manager = CollectionJobManager(tmp_path)

    def fail():
        raise RuntimeError("private-token and /private/database/path")

    receipt = manager.submit("failure", fail, "TEST_OPERATION_FAILED")
    job = completed(manager, receipt)
    assert job["status"] == "failed"
    assert job["error"]["code"] == "TEST_OPERATION_FAILED"
    assert job["error"]["error_id"] == receipt["job_id"]
    assert "private" not in json.dumps(job)
    assert CollectionJobManager(tmp_path).get(receipt["job_id"]) == job
    manager.close(timeout=3)


def test_unconfirmed_result_is_not_reported_as_completed_or_replayed(
    tmp_path, monkeypatch
):
    manager = CollectionJobManager(tmp_path)
    original = collection_jobs.write_json
    calls = []

    def write(path, value, **kwargs):
        if value["status"] == "completed":
            raise OSError("synthetic disk full")
        return original(path, value, **kwargs)

    monkeypatch.setattr(collection_jobs, "write_json", write)
    receipt = manager.submit("write", lambda: calls.append(True) or {}, "TEST_FAILED")
    assert completed(manager, receipt)["status"] == "interrupted"
    assert (
        CollectionJobManager(tmp_path).get(receipt["job_id"])["status"] == "interrupted"
    )
    assert calls == [True]
    manager.close(timeout=3)


def test_close_cancels_queued_work_and_rejects_new_jobs(tmp_path):
    manager = CollectionJobManager(tmp_path)
    entered, release = threading.Event(), threading.Event()

    def work():
        entered.set()
        assert release.wait(5)
        return {}

    try:
        a = manager.submit("running", work, "TEST_FAILED")
        assert entered.wait(2)
        b = manager.submit(
            "queued", lambda: pytest.fail("cancelled work ran"), "TEST_FAILED"
        )
        manager.close()
        assert manager.get(b["job_id"])["status"] == "cancelled"
        with pytest.raises(JobQueueFull):
            manager.submit("closed", dict, "TEST_FAILED")
        release.set()
        assert completed(manager, a)["status"] == "cancelled"
        assert len(list(manager.root.glob("*.json"))) == 2
    finally:
        release.set()
        manager.close(timeout=3)


def test_close_cancels_selected_work_that_has_not_started(tmp_path, monkeypatch):
    manager = CollectionJobManager(tmp_path)
    selected, release = threading.Event(), threading.Event()
    execute = manager._execute
    calls = []

    def pause_before_start(entry):
        selected.set()
        assert release.wait(5)
        execute(entry)

    monkeypatch.setattr(manager, "_execute", pause_before_start)
    try:
        receipt = manager.submit("write", lambda: calls.append(True) or {}, "FAILED")
        assert selected.wait(2)
        assert manager.get(receipt["job_id"])["status"] == "queued"
        manager.close()
    finally:
        release.set()
        manager.close(timeout=3)
    assert manager.get(receipt["job_id"])["status"] == "cancelled"
    assert calls == []


def test_explicit_job_id_is_durable_and_list_projects_operation_receipts(tmp_path):
    manager = CollectionJobManager(tmp_path)
    job_id = "a" * 32
    try:
        receipt = manager.submit(
            "manual_review_receipt", lambda: {"ok": True}, "FAILED", job_id=job_id
        )
        assert receipt["job_id"] == job_id
        assert completed(manager, receipt)["status"] == "completed"
        listed = manager.list(operation="manual_review_receipt")
        assert [item["job_id"] for item in listed] == [job_id]
        assert manager.list(operation="other") == []
        with pytest.raises(ValueError, match="already exists"):
            manager.submit("duplicate", dict, "FAILED", job_id=job_id)
    finally:
        manager.close(timeout=3)

"""Real queue stop races, deadline bounds, and durable worker-exit receipts."""

import json
import threading

import pytest

from src.collection_job_control import job_wait
from src.collection_jobs import CollectionJobManager, JobQueueFull
from tools.test.collection_job_checks import wait_for_job


def finish(manager, receipt):
    return wait_for_job(manager.get, receipt["job_id"])


def test_cancel_queued_job_persists_before_releasing_capacity(tmp_path):
    manager = CollectionJobManager(tmp_path, capacity=2)
    entered, release = threading.Event(), threading.Event()

    def running():
        entered.set()
        assert release.wait(5)
        return {}

    try:
        first = manager.submit("running", running, "FAILED")
        assert entered.wait(2)
        queued = manager.submit(
            "queued", lambda: pytest.fail("cancelled work ran"), "FAILED"
        )
        cancelled = manager.cancel(queued["job_id"])
        assert cancelled["status"] == "cancelled"
        assert cancelled["started_at"] is None
        assert cancelled["finished_at"]
        assert cancelled["owner_id"] == first["owner_id"]
        assert len(cancelled["owner_id"]) == 32
        saved = (manager.root / f"{queued['job_id']}.json").read_bytes()
        assert json.loads(saved) == cancelled
        assert manager.cancel(queued["job_id"]) == cancelled
        replacement = manager.submit("replacement", lambda: {}, "FAILED")
        release.set()
        assert finish(manager, first)["status"] == "completed"
        assert finish(manager, replacement)["status"] == "completed"
        assert (manager.root / f"{queued['job_id']}.json").read_bytes() == saved
    finally:
        release.set()
        manager.close(timeout=3)


def test_running_cancel_interrupts_wait_and_keeps_confirmed_outputs(tmp_path):
    manager = CollectionJobManager(tmp_path)
    entered = threading.Event()
    evidence = tmp_path / "evidence.txt"
    calls = []

    def work():
        evidence.write_text("confirmed", encoding="utf-8")
        entered.set()
        job_wait(30)
        calls.append("late phase")
        return {}

    try:
        receipt = manager.submit("write", work, "FAILED")
        assert entered.wait(2)
        assert manager.cancel(receipt["job_id"])["status"] == "cancelling"
        job = finish(manager, receipt)
        assert job["status"] == "cancelled"
        assert job["error"]["code"] == "COLLECTION_JOB_CANCELLED"
        assert job["cancel_requested_at"] and job["finished_at"]
        assert evidence.read_text(encoding="utf-8") == "confirmed"
        assert calls == []
    finally:
        manager.close(timeout=3)


def test_uncooperative_work_retains_slot_until_exit_and_cannot_complete_late(tmp_path):
    manager = CollectionJobManager(tmp_path, capacity=1)
    entered, release = threading.Event(), threading.Event()

    def work():
        entered.set()
        assert release.wait(5)
        return {"late": True}

    try:
        receipt = manager.submit("blocking", work, "FAILED")
        assert entered.wait(2)
        manager.cancel(receipt["job_id"])
        job = manager.get(receipt["job_id"])
        assert job["status"] == "cancelling" and job["finished_at"] is None
        with pytest.raises(JobQueueFull):
            manager.submit("overlap", lambda: pytest.fail("overlapping work"), "FAILED")
        release.set()
        assert finish(manager, receipt)["status"] == "cancelled"
    finally:
        release.set()
        manager.close(timeout=3)


def test_deadline_expires_queued_job_without_running_it(tmp_path):
    manager = CollectionJobManager(tmp_path)
    entered, release = threading.Event(), threading.Event()

    def work():
        entered.set()
        assert release.wait(5)
        return {}

    try:
        running = manager.submit("running", work, "FAILED")
        assert entered.wait(2)
        queued = manager.submit(
            "expires",
            lambda: pytest.fail("expired work ran"),
            "FAILED",
            timeout_seconds=0.05,
        )
        expired = finish(manager, queued)
        assert expired["status"] == "timed_out"
        assert expired["started_at"] is None
        assert expired["error"]["code"] == "COLLECTION_JOB_TIMED_OUT"
        release.set()
        assert finish(manager, running)["status"] == "completed"
    finally:
        release.set()
        manager.close(timeout=3)


def test_running_deadline_interrupts_wait_and_next_job_has_fresh_context(tmp_path):
    manager = CollectionJobManager(tmp_path)
    entered = threading.Event()

    def slow():
        entered.set()
        job_wait(30)
        pytest.fail("expired operation continued")

    try:
        receipt = manager.submit("slow", slow, "FAILED")
        assert entered.wait(2)
        # Exercise the timer callback after the running receipt is durable.
        manager._expire(receipt["job_id"])
        expired = finish(manager, receipt)
        assert expired["status"] == "timed_out"
        assert expired["started_at"] and expired["finished_at"]
        following = manager.submit("following", lambda: job_wait(0) or {}, "FAILED")
        assert finish(manager, following)["status"] == "completed"
    finally:
        manager.close(timeout=3)


def test_failed_cancellation_write_does_not_stop_or_remove_queued_work(
    tmp_path, monkeypatch
):
    manager = CollectionJobManager(tmp_path)
    entered, release = threading.Event(), threading.Event()
    save = manager._save
    calls = []

    def work():
        entered.set()
        assert release.wait(5)
        return {}

    def fail_cancel(receipt):
        if receipt["status"] == "cancelled":
            raise OSError("synthetic disk full")
        save(receipt)

    try:
        manager.submit("running", work, "FAILED")
        assert entered.wait(2)
        queued = manager.submit("queued", lambda: calls.append(True) or {}, "FAILED")
        monkeypatch.setattr(manager, "_save", fail_cancel)
        with pytest.raises(OSError, match="disk full"):
            manager.cancel(queued["job_id"])
        assert manager.get(queued["job_id"])["status"] == "queued"
        release.set()
        assert finish(manager, queued)["status"] == "completed"
        assert calls == [True]
    finally:
        release.set()
        manager.close(timeout=3)


def test_worker_exit_is_persisted_and_cancels_remaining_work(tmp_path):
    manager = CollectionJobManager(tmp_path)
    entered, release = threading.Event(), threading.Event()

    def fatal():
        entered.set()
        assert release.wait(5)
        raise SystemExit("private worker exit")

    try:
        receipt = manager.submit("fatal", fatal, "FAILED")
        assert entered.wait(2)
        queued = manager.submit(
            "queued", lambda: pytest.fail("orphaned work ran"), "FAILED"
        )
        release.set()
        interrupted = finish(manager, receipt)
        assert interrupted["status"] == "interrupted"
        assert interrupted["finished_at"]
        assert "private" not in json.dumps(interrupted)
        assert finish(manager, queued)["status"] == "cancelled"
        assert (
            json.loads(
                (manager.root / f"{receipt['job_id']}.json").read_text(encoding="utf-8")
            )
            == interrupted
        )
        with pytest.raises(JobQueueFull):
            manager.submit("closed", lambda: {}, "FAILED")
    finally:
        release.set()
        manager.close(timeout=3)


def test_worker_start_failure_is_durable_and_does_not_consume_capacity(
    tmp_path, monkeypatch
):
    manager = CollectionJobManager(tmp_path, capacity=1)
    job_id = "d" * 32
    start = threading.Thread.start

    def fail_worker_start(thread):
        if thread.name == "collection-operations":
            raise RuntimeError("synthetic thread limit")
        start(thread)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(threading.Thread, "start", fail_worker_start)
            with pytest.raises(RuntimeError, match="thread limit"):
                manager.submit(
                    "unstarted",
                    lambda: pytest.fail("unstarted work ran"),
                    "FAILED",
                    job_id=job_id,
                )
        receipt = manager.get(job_id)
        assert receipt["status"] == "interrupted"
        assert receipt["started_at"] is None and receipt["finished_at"]
        assert json.loads((manager.root / f"{job_id}.json").read_bytes()) == receipt
        following = manager.submit("following", lambda: {}, "FAILED")
        assert finish(manager, following)["status"] == "completed"
    finally:
        manager.close(timeout=3)


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), True])
def test_invalid_deadline_cannot_create_a_receipt(tmp_path, timeout):
    manager = CollectionJobManager(tmp_path)
    with pytest.raises(ValueError, match="timeout"):
        manager.submit(
            "invalid",
            lambda: pytest.fail("invalid job ran"),
            "FAILED",
            timeout_seconds=timeout,
        )
    assert not manager.root.exists()

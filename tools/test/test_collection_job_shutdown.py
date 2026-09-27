"""Shutdown requests stop without acknowledging work that has not exited."""

import threading

import pytest

from src.collection_job_control import job_wait
from src.collection_jobs import CollectionJobManager, JobQueueFull


def test_close_interrupts_active_wait_and_persists_exit(tmp_path):
    manager = CollectionJobManager(tmp_path)
    entered = threading.Event()

    def work():
        entered.set()
        job_wait(30)
        pytest.fail("shutdown did not stop active work")

    receipt = manager.submit("maintenance", work, "FAILED")
    assert entered.wait(2)
    assert manager.close(timeout=3)
    result = manager.get(receipt["job_id"])
    assert result["status"] == "cancelled"
    assert result["finished_at"] and result["cancel_requested_at"]
    assert result["result"] is None
    assert manager.close(timeout=3)


def test_close_retains_uncooperative_work_until_actual_exit(tmp_path):
    manager = CollectionJobManager(tmp_path)
    entered, release = threading.Event(), threading.Event()

    def work():
        entered.set()
        assert release.wait(5)
        return {"late": True}

    try:
        receipt = manager.submit("maintenance", work, "FAILED")
        assert entered.wait(2)
        assert not manager.close()
        result = manager.get(receipt["job_id"])
        assert result["status"] == "cancelling"
        assert result["finished_at"] is None
        with pytest.raises(JobQueueFull):
            manager.submit("late", dict, "FAILED")
        release.set()
        assert manager.close(timeout=3)
        result = manager.get(receipt["job_id"])
        assert result["status"] == "cancelled"
        assert result["result"] is None
    finally:
        release.set()
        manager.close(timeout=3)


def test_close_signals_stop_when_receipt_write_fails(tmp_path, monkeypatch):
    manager = CollectionJobManager(tmp_path)
    entered = threading.Event()

    def work():
        entered.set()
        job_wait(30)
        pytest.fail("receipt failure prevented shutdown")

    receipt = manager.submit("maintenance", work, "FAILED")
    assert entered.wait(2)
    save = manager._save

    def fail_request(value):
        if value["status"] == "cancelling":
            raise OSError("disk unavailable")
        save(value)

    monkeypatch.setattr(manager, "_save", fail_request)
    assert manager.close(timeout=3)
    assert manager.get(receipt["job_id"])["status"] == "cancelled"

"""Operator cancellation and timeout receipts through the real HTTP listener."""

import json
import threading
from types import SimpleNamespace

import pytest

from src import collection_http_server, collection_jobs, server
from src.collection_job_control import job_wait
from tools.test.test_collection_job_http import (
    HEADERS,
    fetch,
    finish,
)
from tools.test.test_collection_job_http import (
    job_api as job_api,  # noqa: PLC0414
)
from tools.test.test_http_write_access import (
    WORKER_HEADERS,
)
from tools.test.test_http_write_access import (
    configured_api as configured_api,  # noqa: PLC0414
)
from tools.test.test_quality_http_guards import api as api  # noqa: PLC0414

CANCEL = "/api/collection/jobs/cancel"
MAINTENANCE = "/api/collection/details/prepare_replay"


def cancel(api, job_id, headers=HEADERS):
    return api("POST", CANCEL, json.dumps({"job_id": job_id}).encode(), headers)


def test_cancel_requires_operator_and_waits_for_actual_worker_exit(
    job_api, monkeypatch, tmp_path
):
    entered, release = threading.Event(), threading.Event()
    reloads = []

    def run(**_options):
        entered.set()
        assert release.wait(5)
        return {"prepared_count": 1}

    monkeypatch.setattr(
        server,
        "_detail_collection_service",
        lambda _: SimpleNamespace(prepare_replay=run),
    )
    monkeypatch.setattr(server, "load_data", lambda _: reloads.append(True))
    try:
        status, _, raw = job_api("POST", MAINTENANCE, b'{"dry_run":false}', HEADERS)
        assert status == 202
        accepted = json.loads(raw)
        assert accepted["cancel_url"] == CANCEL
        assert entered.wait(2)
        for headers in ({}, WORKER_HEADERS, {"X-FAPAI-Control-Token": "wrong"}):
            assert cancel(job_api, accepted["job_id"], headers)[0] == 403
            assert fetch(job_api, accepted["status_url"])["status"] == "running"
        status, _, body = cancel(job_api, accepted["job_id"])
        assert status == 200
        assert json.loads(body)["status"] == "cancelling"
        assert fetch(job_api, accepted["status_url"])["finished_at"] is None
    finally:
        release.set()
    job = finish(job_api, raw)
    assert job["status"] == "cancelled"
    assert job["error"]["code"] == "COLLECTION_JOB_CANCELLED"
    assert reloads == []
    assert not (tmp_path / "avm" / "archive_detail_replay.json").exists()
    assert json.loads(cancel(job_api, accepted["job_id"])[2]) == job


@pytest.mark.parametrize("job_id", [None, "", "../outside", "f" * 31, [], {}])
def test_cancel_rejects_invalid_ids_without_creating_receipts(
    job_api, job_id, tmp_path
):
    status, _, raw = cancel(job_api, job_id)
    assert status == 400
    assert json.loads(raw)["error"]["code"] == "COLLECTION_JOB_INVALID_ID"
    assert not (tmp_path / "runtime").exists()


def test_cancel_unknown_job_and_nonobject_body(job_api):
    status, _, raw = cancel(job_api, "a" * 32)
    assert status == 404
    assert json.loads(raw)["error"]["code"] == "COLLECTION_JOB_NOT_FOUND"
    assert job_api("POST", CANCEL, b"[]", HEADERS)[0] == 400


@pytest.mark.parametrize("state", ["queued", "running", "cancelling"])
def test_cancel_cannot_change_an_unowned_receipt_after_restart(
    job_api, tmp_path, state
):
    root = tmp_path / "runtime" / "collection-jobs"
    root.mkdir(parents=True)
    job_id = "b" * 32
    path = root / f"{job_id}.json"
    original = json.dumps(
        {"job_id": job_id, "status": state, "owner_id": "previous"}
    ).encode()
    path.write_bytes(original)
    status, _, raw = cancel(job_api, job_id)
    assert status == 409
    assert json.loads(raw)["error"]["code"] == "COLLECTION_JOB_NOT_OWNED"
    assert (
        fetch(job_api, "/api/collection/jobs?id=" + job_id)["status"] == "interrupted"
    )
    assert path.read_bytes() == original


def test_corrupt_cancel_receipt_is_preserved_without_error_details(job_api, tmp_path):
    root = tmp_path / "runtime" / "collection-jobs"
    root.mkdir(parents=True)
    job_id = "c" * 32
    path = root / f"{job_id}.json"
    path.write_bytes(b'{"partial":')
    status, _, raw = cancel(job_api, job_id)
    assert status == 503
    assert json.loads(raw)["error"]["code"] == "COLLECTION_JOB_STATE_UNAVAILABLE"
    assert str(tmp_path).encode() not in raw
    assert path.read_bytes() == b'{"partial":'


def test_deadline_stops_maintenance_before_report_publication(
    job_api, monkeypatch, tmp_path
):
    manager_type = collection_jobs.CollectionJobManager
    monkeypatch.setattr(
        collection_http_server,
        "CollectionJobManager",
        lambda root, **_: manager_type(root, timeout_seconds=0.05),
    )

    def run(**_options):
        job_wait(30)
        pytest.fail("timed out maintenance continued")

    monkeypatch.setattr(
        server,
        "_detail_collection_service",
        lambda _: SimpleNamespace(prepare_replay=run),
    )
    status, _, raw = job_api("POST", MAINTENANCE, b"{}", HEADERS)
    assert status == 202
    job = finish(job_api, raw)
    assert job["status"] == "timed_out", json.dumps(job)
    assert job["error"]["code"] == "COLLECTION_JOB_TIMED_OUT"
    assert job["deadline_at"] and job["timeout_seconds"] == 0.05
    assert not (tmp_path / "avm").exists()

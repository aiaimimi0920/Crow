"""Receipt preparation captures dependencies without performing durable writes."""

from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest

from src.manual_review_write_contracts import ReviewWriteHost
from src.manual_review_write_handlers import bind_review_writes

SUMMARIES = (
    "manual_review_receipt_jobs_summary",
    "manual_review_control_plane_storage",
    "manual_review_control_plane_backup",
    "manual_review_control_plane_backup_repairs_summary",
    "manual_review_control_plane_integrity",
    "manual_review_control_plane_integrity_history_summary",
    "manual_review_control_plane_stability",
    "manual_review_control_plane_guidance",
)


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    from src import collection_job_control

    events = []

    def record(name, result):
        def run(*args, **kwargs):
            events.append(name)
            return result

        return Mock(side_effect=run)

    monkeypatch.setattr(
        collection_job_control, "job_checkpoint", record("checkpoint", None)
    )
    context = {
        key: {"initial": key}
        for key in (*SUMMARIES, "manual_review_receipt_summary", "operator_overview")
    }
    payload = {
        "action": "review",
        "ready_signal": "ready",
        "status": "resolved",
        "payload": {"nested": {"value": 1}},
        "resolution_notes": " reviewed ",
        "source": " operator ",
    }
    host = SimpleNamespace(
        DB_REPOSITORY=SimpleNamespace(enabled=True),
        _normalize_manual_review_maintenance_options=Mock(
            return_value={"dry_run": True}
        ),
        _manual_review_receipt_store_path=Mock(return_value=tmp_path / "receipt.json"),
        _manual_review_receipt_operations_path=Mock(
            return_value=tmp_path / "operations.json"
        ),
        upsert_manual_review_receipt=record(
            "upsert", {"operation": "updated", "receipt": {"saved": True}}
        ),
        append_manual_review_receipt_operation=record("append", None),
        run_recent_enrich_maintenance=record(
            "maintenance", {"operator_overview": {"new": True}}
        ),
        _manual_review_receipt_context=record("context", context),
        list_manual_review_receipts=Mock(return_value={"receipts": []}),
    )
    for key in SUMMARIES:
        setattr(host, "_" + key, record(key, {"fresh": key}))
    owner = bind_review_writes(cast(ReviewWriteHost, host))
    return host, owner, payload, events, tmp_path


def test_prepared_work_captures_callbacks_repository_and_deep_payload(prepared):
    host, owner, payload, events, root = prepared
    work = owner._prepare_manual_review_receipt_submission(
        root, payload, "async", maintenance_job_id="job-1"
    )
    assert events == []
    assert work.preview["operation"] == "created"
    assert not (root / "receipt.json").exists()
    repository = host.DB_REPOSITORY
    upsert = host.upsert_manual_review_receipt
    append = host.append_manual_review_receipt_operation
    maintenance = host.run_recent_enrich_maintenance
    payload["payload"]["nested"]["value"] = 2
    host.DB_REPOSITORY = SimpleNamespace(enabled=False)
    for name in (
        "upsert_manual_review_receipt",
        "append_manual_review_receipt_operation",
        "run_recent_enrich_maintenance",
        "_manual_review_receipt_context",
        *("_" + key for key in SUMMARIES),
    ):
        setattr(host, name, Mock(side_effect=AssertionError("late replacement")))
    result = work()
    assert events == [
        "checkpoint",
        "upsert",
        "context",
        "checkpoint",
        "maintenance",
        "checkpoint",
        "append",
        *SUMMARIES,
    ]
    receipt = upsert.call_args.args[1]
    assert receipt["payload"] == {"nested": {"value": 1}}
    assert receipt["resolution_notes"] == "reviewed"
    assert receipt["source"] == "operator"
    assert upsert.call_args.kwargs["repository"] is repository
    maintenance.assert_called_once_with(
        data_root=root, repository=repository, dry_run=True
    )
    assert append.call_args.kwargs["maintenance_job_id"] == "job-1"
    assert result["maintenance_job_status"] == "completed"
    assert result["maintenance_triggered"] is True
    assert result["operator_overview"] == {"new": True}
    for key in SUMMARIES:
        assert result[key] == {"fresh": key}


@pytest.mark.parametrize("preview_failure", [False, True])
def test_preview_is_read_only_and_can_degrade(prepared, preview_failure):
    host, owner, payload, events, root = prepared
    if preview_failure:
        host.list_manual_review_receipts.side_effect = OSError("preview unavailable")
    else:
        host.list_manual_review_receipts.return_value = {
            "receipts": [{"action": " review ", "ready_signal": " ready "}]
        }
    work = owner._prepare_manual_review_receipt_submission(root, payload, "sync")
    assert work.preview["operation"] == ("created" if preview_failure else "updated")
    assert events == []
    host.upsert_manual_review_receipt.assert_not_called()
    assert work()["maintenance_triggered"] is True


@pytest.mark.parametrize(
    "stage,mode,code",
    [
        (
            "upsert_manual_review_receipt",
            "sync",
            "AVM_MANUAL_REVIEW_RECEIPT_UPSERT_FAILED",
        ),
        (
            "_manual_review_receipt_context",
            "sync",
            "AVM_MANUAL_REVIEW_RECEIPT_UPSERT_FAILED",
        ),
        (
            "run_recent_enrich_maintenance",
            "sync",
            "AVM_MANUAL_REVIEW_RECEIPT_MAINTENANCE_FAILED",
        ),
        (
            "append_manual_review_receipt_operation",
            "sync",
            "AVM_MANUAL_REVIEW_RECEIPT_SYNC_FINALIZE_FAILED",
        ),
        (
            "append_manual_review_receipt_operation",
            "async",
            "AVM_MANUAL_REVIEW_RECEIPT_ASYNC_FINALIZE_FAILED",
        ),
        (
            "_manual_review_control_plane_guidance",
            "async",
            "AVM_MANUAL_REVIEW_RECEIPT_ASYNC_FINALIZE_FAILED",
        ),
    ],
)
def test_worker_stage_errors_preserve_public_code(prepared, stage, mode, code):
    from src.collection_jobs import CollectionJobFailure

    host, owner, payload, _, root = prepared
    getattr(host, stage).side_effect = RuntimeError("private diagnostic")
    work = owner._prepare_manual_review_receipt_submission(root, payload, mode)
    with pytest.raises(CollectionJobFailure) as raised:
        work()
    assert raised.value.code == code
    assert isinstance(raised.value.__cause__, RuntimeError)
    if stage in ("upsert_manual_review_receipt", "_manual_review_receipt_context"):
        host.run_recent_enrich_maintenance.assert_not_called()
    if stage == "run_recent_enrich_maintenance":
        host.append_manual_review_receipt_operation.assert_not_called()


def test_native_review_write_descriptor_and_context():
    from src import manual_review_write_handlers, server

    handler = object.__new__(server.DataHandler)
    method = handler._post_manual_review_receipt
    assert method.__self__ is handler
    for name in manual_review_write_handlers.ReviewWriteHandlers.__all__:
        function = getattr(server, name)
        assert function.__module__ == manual_review_write_handlers.__name__
        assert getattr(server._CONTEXT, name) is function
    assert method.__func__ is server._post_manual_review_receipt

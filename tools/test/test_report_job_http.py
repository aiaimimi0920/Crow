"""Heavy report generation must release the request thread before computation."""

import importlib
import json
import threading
from pathlib import Path

import pytest

from src import archive_json_io, server
from tools.test.test_collection_job_http import HEADERS, fetch, finish
from tools.test.test_collection_job_http import job_api as job_api
from tools.test.test_http_write_access import configured_api as configured_api
from tools.test.test_quality_http_guards import api as api

REPORTS = (
    ("/api/avm/drift_status", "tools.check_feature_drift", "generate_drift_report"),
    (
        "/api/analysis/drift_status",
        "tools.check_feature_drift",
        "generate_drift_report",
    ),
    ("/api/avm/release_gate", "tools.avm_release_gate", "generate_release_gate_report"),
    (
        "/api/analysis/release_gate",
        "tools.avm_release_gate",
        "generate_release_gate_report",
    ),
    (
        "/api/avm/recent_gap_audit",
        "tools.audit_recent_avm_gaps",
        "build_recent_gap_audit",
    ),
)


@pytest.mark.parametrize("path,module,function", REPORTS)
def test_report_generation_is_polled(
    job_api, monkeypatch, path, module, function, tmp_path
):
    entered, release = threading.Event(), threading.Event()
    calls = []

    def generate(**options):
        calls.append(options)
        entered.set()
        assert release.wait(5)
        return {"pass": False, "assessment": "insufficient-data"}

    monkeypatch.setattr(importlib.import_module(module), function, generate)
    monkeypatch.setattr(
        server,
        "_avm_operator_eval_summary",
        lambda *_args, **_kwargs: {"summary": "available"},
    )
    try:
        status, _, raw = job_api("POST", path, b'{"window_days":0}', HEADERS)
        assert status == 202, raw
        assert entered.wait(2)
        assert fetch(job_api, json.loads(raw)["status_url"])["status"] == "running"
    finally:
        release.set()
    job = finish(job_api, raw)
    assert job["status"] == "completed", job
    assert job["result"]["pass"] is False
    assert job["result"]["assessment"] == "insufficient-data"
    assert len(calls) == 1
    assert calls[0]["window_days"] == 0
    if "release_gate" in path:
        assert job["result"]["summary"] == "available"
    if "recent_gap_audit" in path:
        saved = tmp_path / "avm" / "recent_gap_audit.json"
        assert json.loads(saved.read_text(encoding="utf-8")) == job["result"]


def test_gap_report_publish_failure_keeps_confirmed_bytes(
    job_api, monkeypatch, tmp_path
):
    report = tmp_path / "avm" / "recent_gap_audit.json"
    report.parent.mkdir(parents=True)
    before = b'{"previous":"confirmed"}'
    report.write_bytes(before)
    original_replace = archive_json_io.os.replace

    def replace(source, target):
        if Path(target) == report:
            raise OSError("simulated report publication failure")
        return original_replace(source, target)

    module = importlib.import_module("tools.audit_recent_avm_gaps")
    monkeypatch.setattr(
        module, "build_recent_gap_audit", lambda **_options: {"new": "report"}
    )
    monkeypatch.setattr(archive_json_io.os, "replace", replace)
    status, _, raw = job_api("POST", "/api/avm/recent_gap_audit", b"{}", HEADERS)
    assert status == 202, raw
    job = finish(job_api, raw)
    assert job["status"] == "failed"
    assert job["error"]["code"] == "AVM_RECENT_GAP_AUDIT_FAILED"
    assert report.read_bytes() == before
    assert any(path != report for path in report.parent.iterdir())

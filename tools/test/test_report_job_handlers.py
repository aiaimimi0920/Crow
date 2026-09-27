"""Report job HTTP admission captures its data root, generator and summary."""

import importlib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

CASES = [
    (
        "_post_drift_report",
        "tools.check_feature_drift",
        "generate_drift_report",
        {"window_days": 30},
    ),
    (
        "_post_release_gate",
        "tools.avm_release_gate",
        "generate_release_gate_report",
        {"window_days": 7, "min_sample_size": 1000, "smoke_sample_size": 0},
    ),
    (
        "_post_recent_gap_audit",
        "tools.audit_recent_avm_gaps",
        "build_recent_gap_audit",
        {"window_days": 7, "sample_limit": 20},
    ),
]


@pytest.mark.parametrize("name", [case[0] for case in CASES])
def test_native_report_descriptor(name):
    from src import report_job_handlers, server

    handler = object.__new__(server.DataHandler)
    method = getattr(handler, name)
    assert method.__self__ is handler
    assert method.__func__ is getattr(server, name)
    assert method.__module__ == report_job_handlers.__name__
    assert getattr(server._CONTEXT, name) is method.__func__


@pytest.fixture(params=CASES)
def report(request, monkeypatch, tmp_path):
    from src import server

    name, module, function, defaults = request.param
    generator = Mock(return_value={"report": True})
    module = importlib.import_module(module)
    monkeypatch.setattr(module, function, generator)
    monkeypatch.setattr(server, "AVM_SERVICE", SimpleNamespace(data_dir=tmp_path))
    summary = Mock(return_value={"summary": "ready"})
    monkeypatch.setattr(server, "_avm_operator_eval_summary", summary)
    handler = SimpleNamespace(_enqueue_collection_job=Mock())
    return (
        server,
        name,
        module,
        function,
        defaults,
        generator,
        summary,
        handler,
        tmp_path,
    )


@pytest.mark.parametrize("value", [None, "invalid", -1, 0])
def test_report_numeric_values_and_captured_dependencies(report, monkeypatch, value):
    host, name, module, function, defaults, generator, summary, handler, root = report
    payload = {key: value for key in defaults}
    monkeypatch.setattr(host, "_read_json_body", lambda handler: (True, payload))
    getattr(host, name)(handler)
    run = handler._enqueue_collection_job.call_args.args[1]
    monkeypatch.setattr(host, "AVM_SERVICE", SimpleNamespace(data_dir=root / "other"))
    monkeypatch.setattr(
        module, function, Mock(side_effect=AssertionError("generator changed"))
    )
    monkeypatch.setattr(
        host,
        "_avm_operator_eval_summary",
        Mock(side_effect=AssertionError("summary changed")),
    )
    result = run()
    kwargs = generator.call_args.kwargs
    assert {key: kwargs[key] for key in defaults} == (
        {key: 0 for key in defaults} if value == 0 else defaults
    )
    assert kwargs.get("data_root", kwargs.get("archive_dir")) == (
        root / "archive" if name == "_post_drift_report" else root
    )
    if name == "_post_release_gate":
        summary.assert_called_once_with(root, gate_report_override={"report": True})
        assert result["summary"] == "ready"


def test_rejected_body_never_admits_job(report, monkeypatch):
    host, name, _, _, _, generator, _, handler, _ = report
    monkeypatch.setattr(host, "_read_json_body", lambda handler: (False, {}))
    getattr(host, name)(handler)
    handler._enqueue_collection_job.assert_not_called()
    generator.assert_not_called()


def test_release_summary_failure_keeps_stage_code(monkeypatch, tmp_path):
    from src import server
    from src.collection_jobs import CollectionJobFailure
    from tools import avm_release_gate

    monkeypatch.setattr(server, "AVM_SERVICE", SimpleNamespace(data_dir=tmp_path))
    monkeypatch.setattr(server, "_read_json_body", lambda handler: (True, {}))
    monkeypatch.setattr(
        avm_release_gate, "generate_release_gate_report", lambda **kwargs: {}
    )
    monkeypatch.setattr(
        server,
        "_avm_operator_eval_summary",
        Mock(side_effect=ValueError("summary failed")),
    )
    handler = SimpleNamespace(_enqueue_collection_job=Mock())
    server._post_release_gate(handler)
    with pytest.raises(CollectionJobFailure) as caught:
        handler._enqueue_collection_job.call_args.args[1]()
    assert caught.value.code == "AVM_RELEASE_GATE_SUMMARY_FAILED"
    assert isinstance(caught.value.__cause__, ValueError)

"""Pipeline admission preserves guards, root confinement and facade replacement."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

PIPELINE_ROUTES = (
    "_post_analysis_run",
    "_post_start_all_subtasks",
    "_post_run_all_subtasks_sync",
)


@pytest.fixture
def admission(monkeypatch, tmp_path):
    from src import server

    monkeypatch.setattr(server, "AVM_SERVICE", SimpleNamespace(data_dir=tmp_path))
    monkeypatch.setattr(server, "_require_control_plane", Mock(return_value=True))
    monkeypatch.setattr(server, "_read_json_body", Mock(return_value=(True, {})))
    handler = SimpleNamespace(
        _submit_pipeline_job=Mock(),
        _submit_maintenance_job=Mock(),
        send_error_json=Mock(),
    )
    return server, handler


@pytest.mark.parametrize("name", PIPELINE_ROUTES)
def test_guard_precedes_body_and_rejected_body_never_submits(admission, name):
    host, handler = admission
    host._require_control_plane.return_value = False
    getattr(host, name)(handler)
    host._read_json_body.assert_not_called()
    host._require_control_plane.return_value = True
    host._read_json_body.return_value = False, {}
    getattr(host, name)(handler)
    handler._submit_pipeline_job.assert_not_called()


def test_resolver_tracks_current_root_and_rejects_sibling(
    admission, tmp_path, monkeypatch
):
    host, _ = admission
    root = tmp_path / "root"
    host.AVM_SERVICE.data_dir = root
    assert host._resolve_pipeline_data_dir(None) == str(root.resolve())
    assert host._resolve_pipeline_data_dir("") == str(root.resolve())
    assert host._resolve_pipeline_data_dir(root / "nested") == str(
        (root / "nested").resolve()
    )
    assert host._resolve_pipeline_data_dir(tmp_path / "root-other") is None
    assert host._resolve_pipeline_data_dir(root / ".." / "outside") is None
    del host.AVM_SERVICE.data_dir
    monkeypatch.setattr(host, "DATA_DIR", tmp_path)
    assert host._resolve_pipeline_data_dir(None) == str(tmp_path.resolve())


def test_pipeline_invalid_fields_preserve_order(admission, tmp_path):
    host, handler = admission
    host._read_json_body.return_value = (
        True,
        {
            "alerts_threshold": {},
            "alerts_limit": None,
            "data_dir": str(tmp_path.parent),
        },
    )
    host._post_analysis_run(handler)
    error = handler.send_error_json.call_args.kwargs
    assert error["status"] == 400
    assert error["code"] == "AVM_INVALID_PIPELINE_CONFIG"
    assert error["details"] == {
        "invalid_fields": ["alerts_threshold", "alerts_limit", "data_dir"]
    }
    handler._submit_pipeline_job.assert_not_called()


@pytest.mark.parametrize("name", PIPELINE_ROUTES)
def test_pipeline_uses_current_resolver_and_factory(admission, monkeypatch, name):
    host, handler = admission
    resolver = Mock(return_value="injected-root")
    factory = Mock(return_value=object())
    monkeypatch.setattr(host, "_resolve_pipeline_data_dir", resolver)
    monkeypatch.setattr(host, "AVMPipelineConfig", factory)
    getattr(host, name)(handler)
    resolver.assert_called_once_with(None)
    options = {"data_dir": "injected-root"}
    if name == "_post_analysis_run":
        options.update(alerts_threshold=0.15, alerts_limit=500)
    factory.assert_called_once_with(**options)
    assert handler._submit_pipeline_job.call_args.args[0] is factory.return_value


@pytest.mark.parametrize(
    "name,kind,code",
    [
        (
            "_post_detail_maintenance",
            "recent_enrich_maintenance",
            "AVM_RECENT_ENRICH_MAINTENANCE_FAILED",
        ),
        (
            "_post_fetch_missing_detail_archives",
            "fetch_missing_detail_archives",
            "AVM_FETCH_MISSING_DETAIL_ARCHIVES_FAILED",
        ),
        (
            "_post_archive_detail_replay",
            "archive_detail_replay",
            "AVM_ARCHIVE_DETAIL_REPLAY_FAILED",
        ),
    ],
)
def test_maintenance_preserves_delegation(admission, name, kind, code):
    host, handler = admission
    getattr(host, name)(handler)
    handler._submit_maintenance_job.assert_called_once_with(kind, code)
    host._read_json_body.assert_not_called()
    host._require_control_plane.assert_not_called()


def test_native_handlers_bind_descriptors_and_publish_context():
    from src import collection_maintenance_handlers, server
    from src import pipeline_submission_handlers as owner

    handler = object.__new__(server.DataHandler)
    for name in owner.PipelineSubmissionHandlers.__all__:
        function = getattr(server, name)
        expected_owner = (
            collection_maintenance_handlers
            if name in collection_maintenance_handlers.__all__
            else owner
        )
        assert function.__module__ == expected_owner.__name__
        assert getattr(server._CONTEXT, name) is function
        if name.startswith("_post_"):
            method = getattr(handler, name)
            assert method.__self__ is handler
            assert method.__func__ is function

"""Seed submission keeps legacy mode and execution-time callback semantics."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def batch(monkeypatch):
    from src import server

    monkeypatch.setattr(server, "_read_json_body", Mock(return_value=(True, {})))
    monkeypatch.setattr(server, "_require_control_plane", Mock(return_value=True))
    monkeypatch.setattr(
        server, "handle_seed_batch_submission", Mock(return_value={"ok": True})
    )
    handler = SimpleNamespace(
        send_json=Mock(), send_error_json=Mock(), _enqueue_collection_job=Mock()
    )
    return server, handler


@pytest.mark.parametrize("mode", [None, "", "sync", " async ", "unknown", 1])
def test_legacy_sync_mode_preserves_payload_and_no_new_guard(batch, mode):
    host, handler = batch
    payload = {"mode": mode, "items": []}
    host._read_json_body.return_value = True, payload
    host._post_seed_batch(handler)
    assert host.handle_seed_batch_submission.call_args.args[0] is payload
    host._require_control_plane.assert_not_called()
    handler._enqueue_collection_job.assert_not_called()
    handler.send_json.assert_called_once_with({"ok": True})


def test_async_seed_uses_current_callback_with_admitted_payload(batch, monkeypatch):
    host, handler = batch
    payload = {"mode": "ASYNC", "items": []}
    host._read_json_body.return_value = True, payload
    original = host.handle_seed_batch_submission
    host._post_seed_batch(handler)
    kind, run, error = handler._enqueue_collection_job.call_args.args
    assert (kind, error) == ("seed_batch", "AVM_SEED_BATCH_ASYNC_FAILED")
    assert handler._enqueue_collection_job.call_args.kwargs == {
        "response_extra": {"execution_mode": "async"}
    }
    replacement = Mock(return_value={"new": True})
    monkeypatch.setattr(host, "handle_seed_batch_submission", replacement)
    assert run() == {"new": True}
    submitted = replacement.call_args.args[0]
    assert submitted is not payload
    assert submitted["items"] is payload["items"]
    assert "mode" not in submitted
    original.assert_not_called()


def test_rejected_body_precedes_guard_and_denied_async_does_not_submit(batch):
    host, handler = batch
    host._read_json_body.return_value = False, {}
    host._post_seed_batch(handler)
    host._require_control_plane.assert_not_called()
    host._read_json_body.return_value = True, {"mode": "async"}
    host._require_control_plane.return_value = False
    host._post_seed_batch(handler)
    handler._enqueue_collection_job.assert_not_called()
    host.handle_seed_batch_submission.assert_not_called()


def test_async_queue_errors_propagate_while_sync_errors_use_http_envelope(batch):
    host, handler = batch
    host._read_json_body.return_value = True, {"mode": "async"}
    handler._enqueue_collection_job.side_effect = RuntimeError("queue failed")
    with pytest.raises(RuntimeError, match="queue failed"):
        host._post_seed_batch(handler)
    host._read_json_body.return_value = True, {}
    host.handle_seed_batch_submission.side_effect = RuntimeError("sync failed")
    host._post_seed_batch(handler)
    assert handler.send_error_json.call_args.kwargs["code"] == "AVM_SEED_BATCH_FAILED"


def test_seed_batch_native_descriptor():
    from src import seed_task_handlers, server

    handler = object.__new__(server.DataHandler)
    assert handler._post_seed_batch.__self__ is handler
    assert handler._post_seed_batch.__func__ is server._post_seed_batch
    assert server._post_seed_batch.__module__ == seed_task_handlers.__name__
    assert server._CONTEXT._post_seed_batch is server._post_seed_batch

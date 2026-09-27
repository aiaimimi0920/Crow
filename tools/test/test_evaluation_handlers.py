"""Admission snapshots and HTTP exception boundaries for evaluation/inference."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def admission(monkeypatch):
    from src import server

    evaluate = Mock(return_value={"valuation": 1})
    infer = Mock(return_value={"location": "kept"})
    helper = SimpleNamespace(chat_with_glm=Mock(), log_prediction_event=Mock())
    monkeypatch.setattr(
        server, "AVM_SERVICE", SimpleNamespace(evaluate_request=evaluate)
    )
    monkeypatch.setattr(server, "llm_helper", helper)
    monkeypatch.setattr(
        server,
        "_detail_collection_service",
        Mock(return_value=SimpleNamespace(infer_location=infer)),
    )
    monkeypatch.setattr(
        server,
        "_read_json_body",
        Mock(return_value=(True, {"subject": {"area_sqm": 90}})),
    )
    handler = SimpleNamespace(
        send_json=Mock(), send_error_json=Mock(), _enqueue_collection_job=Mock()
    )
    return server, handler, evaluate, infer, helper


@pytest.mark.parametrize("mode", [None, 1, {}, "", "background"])
def test_invalid_execution_mode_is_rejected(admission, mode):
    host, handler, _, _, _ = admission
    assert host._read_execution_mode(handler, {"execution_mode": mode}) is None
    assert handler.send_error_json.call_args.kwargs == {
        "status": 400,
        "code": "AVM_INVALID_EXECUTION_MODE",
        "message": "execution_mode must be 'sync' or 'async'",
        "details": {"allowed": ["sync", "async"]},
    }


def test_execution_mode_default_and_normalization(admission):
    host, handler, _, _, _ = admission
    assert host._read_execution_mode(handler, {}) == "sync"
    assert host._read_execution_mode(handler, {"execution_mode": " ASYNC "}) == "async"
    handler.send_error_json.assert_not_called()


@pytest.mark.parametrize("name", ["_post_analysis_evaluate", "_post_infer_location"])
def test_rejected_body_does_not_resolve_mode_or_service(admission, monkeypatch, name):
    host, handler, evaluate, infer, _ = admission
    mode = Mock()
    monkeypatch.setattr(host, "_read_execution_mode", mode)
    host._read_json_body.return_value = False, {}
    getattr(host, name)(handler)
    mode.assert_not_called()
    evaluate.assert_not_called()
    infer.assert_not_called()
    host._detail_collection_service.assert_not_called()


def test_evaluation_job_captures_service_and_shallow_payload(admission, monkeypatch):
    host, handler, evaluate, _, _ = admission
    payload = {
        "execution_mode": "async",
        "request_id": None,
        "subject": {"area_sqm": 90},
    }
    host._read_json_body.return_value = True, payload
    host._post_analysis_evaluate(handler)
    kind, run, error = handler._enqueue_collection_job.call_args.args
    assert (kind, error) == ("avm_evaluate", "AVM_EVALUATE_ASYNC_FAILED")
    assert handler._enqueue_collection_job.call_args.kwargs == {
        "response_extra": {"execution_mode": "async", "request_id": None}
    }
    replacement = Mock()
    monkeypatch.setattr(
        host, "AVM_SERVICE", SimpleNamespace(evaluate_request=replacement)
    )
    payload["request_id"] = "later"
    assert run() == {"valuation": 1}
    submitted = evaluate.call_args.args[0]
    assert submitted is not payload
    assert submitted["subject"] is payload["subject"]
    assert submitted["request_id"] is None
    assert "execution_mode" not in submitted
    replacement.assert_not_called()


def test_inference_job_captures_factory_and_llm_callbacks(admission, monkeypatch):
    host, handler, _, infer, helper = admission
    host._read_json_body.return_value = (
        True,
        {"execution_mode": "async", "address": "original", "id": None},
    )
    host._post_infer_location(handler)
    kind, run, error = handler._enqueue_collection_job.call_args.args
    assert (kind, error) == ("infer_location", "AVM_DETAIL_INFER_LOCATION_ASYNC_FAILED")
    assert handler._enqueue_collection_job.call_args.kwargs == {
        "response_extra": {"execution_mode": "async", "item_id": None}
    }
    original_chat, original_log = helper.chat_with_glm, helper.log_prediction_event
    helper.chat_with_glm = Mock()
    helper.log_prediction_event = Mock()
    replacement = Mock()
    monkeypatch.setattr(host, "_detail_collection_service", replacement)
    assert run() == {"location": "kept"}
    infer.assert_called_once_with(
        address="original",
        title="",
        item_id=None,
        chat_with_glm=original_chat,
        log_prediction_event=original_log,
    )
    replacement.assert_not_called()


@pytest.mark.parametrize("name", ["_post_analysis_evaluate", "_post_infer_location"])
@pytest.mark.parametrize("failure", ["queue", "response"])
def test_exception_boundary_preserves_evaluation_and_inference_difference(
    admission, name, failure
):
    host, handler, _, _, _ = admission
    payload = {"subject": {"area_sqm": 90}}
    if failure == "queue":
        payload["execution_mode"] = "async"
        handler._enqueue_collection_job.side_effect = RuntimeError("boundary")
    else:
        handler.send_json.side_effect = RuntimeError("boundary")
    host._read_json_body.return_value = True, payload
    if name == "_post_analysis_evaluate":
        with pytest.raises(RuntimeError, match="boundary"):
            getattr(host, name)(handler)
        handler.send_error_json.assert_not_called()
    else:
        getattr(host, name)(handler)
        assert handler.send_error_json.call_args.kwargs["code"] == (
            "AVM_DETAIL_INFER_LOCATION_FAILED"
        )


def test_native_evaluation_handlers_publish_context_and_descriptors():
    from src import evaluation_handlers, location_inference_handlers, server

    handler = object.__new__(server.DataHandler)
    for name in evaluation_handlers.EvaluationHandlers.__all__:
        function = getattr(server, name)
        expected_owner = (
            evaluation_handlers
            if name == "_post_analysis_evaluate"
            else location_inference_handlers
        )
        assert function.__module__ == expected_owner.__name__
        assert getattr(server._CONTEXT, name) is function
        if name.startswith("_post_"):
            assert getattr(handler, name).__self__ is handler
            assert getattr(handler, name).__func__ is function

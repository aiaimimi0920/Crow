import hashlib
import json
import logging
import time

import pytest
import requests

from src import llm_qualification_diagnostics as diagnostics
from src.llm_model_selector import LLMBackendUnavailableError
from src.llm_qualification_transport import ModelHttpError
from tools.test.test_llm_qualification_pool import Response, make_pool


@pytest.mark.parametrize("probe", [False, True])
@pytest.mark.parametrize("status", [401, 403, 429, 503])
def test_http_failure_logs_only_safe_facts(caplog, probe, status):
    error = ModelHttpError(status, 7200)
    error.response_body = "secret provider body"
    error.request_url = "https://user:secret@example.test/?token=secret"
    with caplog.at_level(logging.WARNING, logger=diagnostics.__name__):
        diagnostics.report_request_failure(
            "deepseek-v4-flash", probe=probe, error=error
        )
    event = json.loads(caplog.messages[-1])
    assert event == {
        "kind": "analysis_model_request_failure",
        "model": "sha256:" + hashlib.sha256(b"deepseek-v4-flash").hexdigest(),
        "phase": "qualification" if probe else "business",
        "status_code": status,
        "retry_after_seconds": 7200,
        "error_type": "ModelHttpError",
    }
    assert "secret" not in caplog.text


def test_transport_error_text_and_unsafe_model_id_are_not_logged(caplog):
    error = requests.ReadTimeout("secret credential in a URL or response")
    with caplog.at_level(logging.WARNING, logger=diagnostics.__name__):
        diagnostics.report_request_failure(
            "https://user:secret@example.test/?token=secret", probe=False, error=error
        )
    event = json.loads(caplog.messages[-1])
    assert event["model"].startswith("sha256:")
    assert event["status_code"] is event["retry_after_seconds"] is None
    assert event["error_type"] == "ReadTimeout"
    assert "secret" not in caplog.text and "https" not in caplog.text


@pytest.mark.parametrize(
    "model", ["sk-secret123", "example.test/path", "deepseek-v4-flash"]
)
def test_model_names_are_always_fingerprinted_even_if_they_look_valid(caplog, model):
    with caplog.at_level(logging.WARNING, logger=diagnostics.__name__):
        diagnostics.report_request_failure(
            model, probe=False, error=ModelHttpError(403, 60)
        )
    event = json.loads(caplog.messages[-1])
    assert (
        event["model"] == "sha256:" + hashlib.sha256(model.encode("utf-8")).hexdigest()
    )
    assert model not in caplog.text


@pytest.mark.parametrize(
    "value", [float("inf"), float("nan"), -1, True, "secret", 31_536_001]
)
def test_invalid_retry_after_is_not_published(caplog, value):
    with caplog.at_level(logging.WARNING, logger=diagnostics.__name__):
        diagnostics.report_request_failure(
            "good", probe=True, error=ModelHttpError(503, value)
        )
    assert json.loads(caplog.messages[-1])["retry_after_seconds"] is None


@pytest.mark.parametrize("status", [401, 403, 429, 503])
def test_business_failure_is_logged_before_pool_hides_status_without_extra_calls(
    tmp_path, caplog, status
):
    pool = make_pool(tmp_path, {"good": 5, "peer": 5})
    assert set(pool.ensure()) == {"good", "peer"}
    qualification = pool.store.snapshot()["models"]["good"].copy()
    calls = []

    def rejected(*args, **kwargs):
        calls.append(kwargs["json"]["model"])
        response = Response({"error": "secret provider body"})
        response.status_code = status
        response.headers = {"Retry-After": "7200"}
        return response

    pool.session.post = rejected
    with (
        caplog.at_level(logging.WARNING, logger=diagnostics.__name__),
        pytest.raises(LLMBackendUnavailableError),
    ):
        pool.chat("secret source evidence", model="good")
    events = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == diagnostics.__name__
    ]
    assert len(events) == 1 and events[0]["status_code"] == status
    assert events[0]["phase"] == "business"
    assert events[0]["model"] == "sha256:" + hashlib.sha256(b"good").hexdigest()
    assert calls == ["good"]
    assert "secret" not in caplog.text
    state = pool.store.snapshot()
    assert state["models"]["good"]["score"] == qualification["score"]
    if status in {401, 403, 429}:
        assert state["cooldown_until"] > time.time() + 7190
        assert pool.available() == []
    else:
        assert not state.get("cooldown_until") and pool.available() == ["peer"]
    if status == 429:
        assert state["models"]["good"] == qualification
    else:
        assert state["models"]["good"]["blocked_until"] > time.time() + 890


def test_broken_diagnostic_sink_does_not_change_http_exception_or_backoff(
    tmp_path, monkeypatch
):
    pool = make_pool(tmp_path, {"good": 5})
    assert pool.ensure() == ["good"]

    def broken_logger(*args, **kwargs):
        raise OSError("diagnostic sink unavailable")

    def rejected(*args, **kwargs):
        response = Response({"error": "secret"})
        response.status_code = 403
        response.headers = {}
        return response

    monkeypatch.setattr(diagnostics.logger, "warning", broken_logger)
    pool.session.post = rejected
    with pytest.raises(ModelHttpError) as captured:
        pool.request("good", "secret source evidence")
    assert captured.value.status_code == 403
    assert pool.store.snapshot()["cooldown_until"] > time.time() + 3590

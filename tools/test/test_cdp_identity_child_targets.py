"""Child targets must receive identity before their own first script runs."""

import json

import pytest

from tools.cdp_browser_identity import (
    BrowserIdentityCommandError,
    BrowserIdentityController,
    browser_identity_init_script,
)


def controller_with_recorder(tmp_path, monkeypatch, *, failure_method="", failure=None):
    controller = BrowserIdentityController(
        cdp_endpoint="http://cdp.test",
        user_agent="configured UA",
        full_version="152.0.0.0",
        ready_path=tmp_path / "ready.json",
    )
    sent = []

    def send(method, params=None, *, session_id=""):
        sent.append((method, params or {}, session_id))
        if method == failure_method:
            if isinstance(failure, Exception):
                raise failure
            return failure
        return {}

    monkeypatch.setattr(controller, "_send_and_wait", send)
    return controller, sent


@pytest.mark.parametrize("target_type", ["page", "iframe"])
def test_documents_recursively_attach_children_before_resuming(
    tmp_path, monkeypatch, target_type
):
    controller, sent = controller_with_recorder(tmp_path, monkeypatch)
    controller._apply_to_session("document-session", target_type)

    methods = [item[0] for item in sent]
    assert sent[0][:2] == (
        "Target.setAutoAttach",
        {"autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True},
    )
    assert methods.index("Page.addScriptToEvaluateOnNewDocument") < methods.index(
        "Runtime.runIfWaitingForDebugger"
    )
    assert controller.applied_targets == 1
    assert all(item[2] == "document-session" for item in sent)


def test_worker_initialization_and_nested_attachment_precede_resume(
    tmp_path, monkeypatch
):
    controller, sent = controller_with_recorder(tmp_path, monkeypatch)
    controller._apply_to_session("worker-session", "worker")

    assert [item[0] for item in sent] == [
        "Target.setAutoAttach",
        "Runtime.enable",
        "Runtime.evaluate",
        "Runtime.runIfWaitingForDebugger",
    ]
    assert sent[2][1] == {
        "expression": browser_identity_init_script(),
        "returnByValue": True,
    }
    assert all(item[2] == "worker-session" for item in sent)
    assert controller.applied_targets == 1


@pytest.mark.parametrize(
    "method", ["Target.setAutoAttach", "Runtime.enable", "Runtime.evaluate"]
)
@pytest.mark.parametrize(
    "failure",
    [
        TimeoutError("worker unavailable"),
        BrowserIdentityCommandError(
            "Runtime.evaluate", {"code": -32000, "message": "target closed"}
        ),
    ],
)
def test_worker_setup_failure_always_attempts_one_resume(
    tmp_path, monkeypatch, method, failure
):
    controller, sent = controller_with_recorder(
        tmp_path, monkeypatch, failure_method=method, failure=failure
    )
    with pytest.raises(type(failure)):
        controller._apply_to_session("worker-session", "worker")
    methods = [item[0] for item in sent]
    assert methods[-1] == "Runtime.runIfWaitingForDebugger"
    assert methods.count("Runtime.runIfWaitingForDebugger") == 1
    assert controller.applied_targets == 0


def test_worker_javascript_exception_does_not_count_as_applied(tmp_path, monkeypatch):
    controller, sent = controller_with_recorder(
        tmp_path,
        monkeypatch,
        failure_method="Runtime.evaluate",
        failure={"result": {"exceptionDetails": {"text": "Uncaught"}}},
    )
    with pytest.raises(RuntimeError, match="worker identity initialization failed"):
        controller._apply_to_session("worker-session", "worker")
    assert sent[-1][0] == "Runtime.runIfWaitingForDebugger"
    assert controller.applied_targets == 0


@pytest.mark.parametrize("target_type", ["service_worker", "shared_worker", "other"])
def test_unrelated_target_types_keep_resume_only_behavior(
    tmp_path, monkeypatch, target_type
):
    controller, sent = controller_with_recorder(tmp_path, monkeypatch)
    controller._apply_to_session("other-session", target_type)
    assert [item[0] for item in sent] == ["Runtime.runIfWaitingForDebugger"]
    assert controller.applied_targets == 0


@pytest.mark.parametrize(
    "parent_error", [None, {"code": -32000, "message": "parent failed"}]
)
def test_nested_target_does_not_discard_cached_parent_response_after_deadline(
    tmp_path, monkeypatch, parent_error
):
    from tools import cdp_browser_identity

    controller = BrowserIdentityController(
        cdp_endpoint="http://cdp.test",
        user_agent="UA",
        full_version="152.0.0.0",
        ready_path=tmp_path / "ready.json",
    )
    now = [0.0]
    monkeypatch.setattr(cdp_browser_identity.time, "monotonic", lambda: now[0])

    class Socket:
        def __init__(self):
            parent = {"id": 1, "result": {"accepted": True}}
            if parent_error:
                parent = {"id": 1, "error": parent_error}
            self.replies = [
                {"method": "Target.attachedToTarget"},
                parent,
                {"id": 2, "result": {}},
            ]

        def send(self, payload):
            pass

        def recv(self):
            return json.dumps(self.replies.pop(0))

    controller.ws = Socket()

    def process_child(_message):
        controller._send_and_wait("Runtime.enable", session_id="child")
        now[0] = 6.0

    monkeypatch.setattr(controller, "_handle_message", process_child)
    if parent_error:
        with pytest.raises(BrowserIdentityCommandError, match="parent failed"):
            controller._send_and_wait("Target.setAutoAttach")
    else:
        assert controller._send_and_wait("Target.setAutoAttach")["result"] == {
            "accepted": True
        }
    assert controller.command_responses == {}

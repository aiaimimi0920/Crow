"""An already-correct locale must not tear down browser identity ownership."""

import json

import pytest

from tools.cdp_browser_identity import (
    BrowserIdentityCommandError,
    BrowserIdentityController,
)


def controller_with_locale_error(tmp_path, error, effective_locale="zh-CN"):
    sent = []

    class Socket:
        def __init__(self):
            self.responses = []

        def send(self, payload):
            message = json.loads(payload)
            sent.append(message)
            response = {"id": message["id"], "result": {}}
            if message["method"] == "Emulation.setLocaleOverride":
                response = {"id": message["id"], "error": error}
            elif message[
                "method"
            ] == "Runtime.evaluate" and "resolvedOptions().locale" in message[
                "params"
            ].get("expression", ""):
                response["result"] = {"result": {"value": effective_locale}}
            self.responses.append(response)

        def recv(self):
            return json.dumps(self.responses.pop(0))

    controller = BrowserIdentityController(
        cdp_endpoint="http://127.0.0.1:9223",
        user_agent="Mozilla/5.0 Chrome/152.0.0.0",
        full_version="152.0.7977.64",
        ready_path=tmp_path / "ready.json",
    )
    controller.ws = Socket()
    return controller, sent


LOCALE_IN_USE = {
    "code": -32000,
    "message": "Another locale override is already in effect",
}


def test_existing_matching_locale_keeps_controller_connected(tmp_path):
    controller, sent = controller_with_locale_error(tmp_path, LOCALE_IN_USE)
    controller._apply_to_session("existing-page", "page")
    assert controller.applied_targets == 1
    assert controller.ws is not None
    methods = [message["method"] for message in sent]
    assert methods.index("Page.addScriptToEvaluateOnNewDocument") < methods.index(
        "Runtime.runIfWaitingForDebugger"
    )
    locale_probe = next(
        index
        for index, message in enumerate(sent)
        if "resolvedOptions().locale" in message["params"].get("expression", "")
    )
    assert methods.index("Runtime.runIfWaitingForDebugger") < locale_probe
    assert all(message["sessionId"] == "existing-page" for message in sent)


def test_existing_different_locale_is_not_silently_accepted(tmp_path):
    controller, sent = controller_with_locale_error(tmp_path, LOCALE_IN_USE, "en-US")
    with pytest.raises(RuntimeError, match="existing locale does not match"):
        controller._apply_to_session("existing-page", "page")
    assert controller.applied_targets == 0
    assert (
        sum(message["method"] == "Runtime.runIfWaitingForDebugger" for message in sent)
        == 1
    )


@pytest.mark.parametrize(
    "error",
    [
        {"code": -32000, "message": "unrelated command failure"},
        {"code": -32601, "message": "Another locale override is already in effect"},
    ],
)
def test_other_locale_errors_still_fail_and_resume_target(tmp_path, error):
    controller, sent = controller_with_locale_error(tmp_path, error)
    with pytest.raises(RuntimeError):
        controller._apply_to_session("existing-page", "page")
    assert controller.applied_targets == 0
    assert [message["method"] for message in sent][
        -1
    ] == "Runtime.runIfWaitingForDebugger"
    assert not any(
        message["method"] == "Page.addScriptToEvaluateOnNewDocument" for message in sent
    )


def test_nested_non_locale_error_is_not_accepted(tmp_path, monkeypatch):
    controller, sent = controller_with_locale_error(tmp_path, LOCALE_IN_USE)
    original = controller._send_and_wait

    def send(method, *args, **kwargs):
        if method == "Emulation.setLocaleOverride":
            raise BrowserIdentityCommandError(
                "Emulation.setUserAgentOverride", LOCALE_IN_USE
            )
        return original(method, *args, **kwargs)

    monkeypatch.setattr(controller, "_send_and_wait", send)
    with pytest.raises(BrowserIdentityCommandError) as failure:
        controller._apply_to_session("existing-page", "page")
    assert failure.value.method == "Emulation.setUserAgentOverride"
    assert controller.applied_targets == 0
    assert sent[-1]["method"] == "Runtime.runIfWaitingForDebugger"


@pytest.mark.parametrize("failure", [TimeoutError("busy"), OSError("offline")])
def test_locale_validation_failure_is_not_silently_accepted(
    tmp_path, monkeypatch, failure
):
    controller, sent = controller_with_locale_error(tmp_path, LOCALE_IN_USE)
    original = controller._send_and_wait

    def send(method, params=None, **kwargs):
        if method == "Runtime.evaluate" and "resolvedOptions().locale" in params.get(
            "expression", ""
        ):
            raise failure
        return original(method, params, **kwargs)

    monkeypatch.setattr(controller, "_send_and_wait", send)
    with pytest.raises(type(failure)):
        controller._apply_to_session("existing-page", "page")
    assert controller.applied_targets == 0
    assert sent[-1]["method"] == "Runtime.runIfWaitingForDebugger"

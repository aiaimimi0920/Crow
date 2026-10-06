"""The persistent identity owner must enable scripts on future documents."""

import pytest

from tools.cdp_browser_identity import (
    BrowserIdentityCommandError,
    BrowserIdentityController,
)


@pytest.mark.parametrize(
    "failure",
    [
        TimeoutError("page domain unavailable"),
        BrowserIdentityCommandError(
            "Page.enable", {"code": -32000, "message": "target closed"}
        ),
    ],
)
def test_page_enable_failure_resumes_target_without_claiming_identity(
    tmp_path, monkeypatch, failure
):
    controller = BrowserIdentityController(
        cdp_endpoint="http://cdp.test",
        user_agent="configured UA",
        full_version="152.0.0.0",
        ready_path=tmp_path / "ready.json",
    )
    sent = []

    def send(method, _params=None, *, session_id=""):
        sent.append((method, session_id))
        if method == "Page.enable":
            raise failure
        return {}

    monkeypatch.setattr(controller, "_send_and_wait", send)
    with pytest.raises(type(failure)):
        controller._apply_to_session("persistent-page-session", "page")
    methods = [method for method, _ in sent]
    assert methods[-1] == "Runtime.runIfWaitingForDebugger"
    assert methods.count("Runtime.runIfWaitingForDebugger") == 1
    assert "Page.addScriptToEvaluateOnNewDocument" not in methods
    assert controller.applied_targets == 0
    assert not controller.ready_path.exists()
    assert all(session == "persistent-page-session" for _, session in sent)

"""Reconnect must not wait for JavaScript in an already-running Worker."""

import json

import pytest

from tools.cdp_browser_identity import BrowserIdentityController


def recorded_controller(tmp_path, monkeypatch):
    controller = BrowserIdentityController(
        cdp_endpoint="http://cdp.test",
        user_agent="UA",
        full_version="152.0.0.0",
        ready_path=tmp_path / "ready.json",
    )
    sent = []

    def command(method, params=None, *, session_id=""):
        sent.append((method, params or {}, session_id))
        if method == "Runtime.evaluate":
            raise TimeoutError("running Worker is busy")
        return {}

    monkeypatch.setattr(controller, "_send_and_wait", command)
    return controller, sent


def attachment(target_type, waiting):
    return {
        "method": "Target.attachedToTarget",
        "params": {
            "sessionId": "session",
            "targetInfo": {"type": target_type},
            "waitingForDebugger": waiting,
        },
    }


def test_running_worker_keeps_child_attachment_without_evaluate_or_resume(
    tmp_path, monkeypatch, capsys
):
    controller, sent = recorded_controller(tmp_path, monkeypatch)

    controller._handle_message(attachment("worker", False))

    assert [row[0] for row in sent] == ["Target.setAutoAttach"]
    assert sent[0][1] == {
        "autoAttach": True,
        "waitForDebuggerOnStart": True,
        "flatten": True,
    }
    assert controller.applied_targets == 0
    event = json.loads(capsys.readouterr().out)
    assert event["event"] == "browser_identity_running_worker_skipped"
    assert event["identity_verified"] is False


@pytest.mark.parametrize("target_type", ["tab", "service_worker", "shared_worker"])
def test_running_unconfigured_target_does_not_send_unnecessary_resume(
    tmp_path, monkeypatch, target_type
):
    controller, sent = recorded_controller(tmp_path, monkeypatch)

    controller._handle_message(attachment(target_type, False))

    assert sent == []
    assert controller.applied_targets == 0


def test_startup_worker_still_initializes_and_resumes_on_failure(tmp_path, monkeypatch):
    controller, sent = recorded_controller(tmp_path, monkeypatch)

    with pytest.raises(TimeoutError, match="running Worker is busy"):
        controller._handle_message(attachment("worker", True))

    assert [row[0] for row in sent] == [
        "Target.setAutoAttach",
        "Runtime.enable",
        "Runtime.evaluate",
        "Runtime.runIfWaitingForDebugger",
    ]
    assert controller.applied_targets == 0


@pytest.mark.parametrize("waiting", [None, 0, "false"])
def test_nonboolean_waiting_marker_does_not_silently_skip_initialization(
    tmp_path, monkeypatch, waiting
):
    controller, sent = recorded_controller(tmp_path, monkeypatch)

    with pytest.raises(TimeoutError):
        controller._handle_message(attachment("worker", waiting))

    assert "Runtime.evaluate" in [row[0] for row in sent]
    assert sent[-1][0] == "Runtime.runIfWaitingForDebugger"


def test_missing_waiting_marker_preserves_initialization(tmp_path, monkeypatch):
    controller, sent = recorded_controller(tmp_path, monkeypatch)
    event = attachment("worker", True)
    del event["params"]["waitingForDebugger"]

    with pytest.raises(TimeoutError):
        controller._handle_message(event)

    assert "Runtime.evaluate" in [row[0] for row in sent]

import inspect
import json

import pytest

from tools import pc2_solver_manual_window as window


def test_options_only_default_when_omitted():
    from tools import pc2_solver_config as config

    assert config.resolve_loop_options("", "", 0, 0) == ("", "", 0, 0)
    assert config.resolve_loop_options(None, None, None, None) == (
        config.DEFAULT_API_BASE_URL, config.DEFAULT_CDP_ENDPOINT,
        config.DEFAULT_POLL_SECONDS, config.DEFAULT_MAX_ATTEMPTS,
    )


@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setattr(window, "REQUEST_PATH", tmp_path / "request.json")
    monkeypatch.setattr(window, "ACK_PATH", tmp_path / "ack.json")
    return {"request_id": "a" * 32, "requested_at": 100.0, "expires_at": 200.0}


@pytest.mark.parametrize("now,active", [(99, False), (100, True), (199, True), (200, False)])
def test_window_has_bounded_start_and_expiry(paths, now, active):
    window.REQUEST_PATH.write_text(json.dumps(paths), encoding="utf-8")
    assert bool(window.active_manual_window(now)) is active


@pytest.mark.parametrize("patch", [
    {"request_id": "secret"}, {"requested_at": True}, {"expires_at": float("inf")},
    {"expires_at": 701}, {"expires_at": "200"}, {"expires_at": 99},
])
def test_invalid_request_cannot_hold_browser_forever(paths, patch):
    window.REQUEST_PATH.write_text(json.dumps({**paths, **patch}), encoding="utf-8")
    assert window.active_manual_window(150) is None


def test_ack_and_heartbeat_without_browser_or_nas_actions(paths, monkeypatch):
    window.REQUEST_PATH.write_text(json.dumps(paths), encoding="utf-8")
    events, beats, sleeps = [], [], []
    monkeypatch.setattr(window.time, "time", lambda: 150)
    monkeypatch.setattr(window.time, "sleep", sleeps.append)
    monkeypatch.setattr(window, "log_event", events.append)
    monkeypatch.setattr(window, "write_solver_heartbeat", beats.append)
    assert window.hold_manual_window(30)
    assert window.hold_manual_window(30)
    assert beats == ["manual_window", "manual_window"]
    assert sleeps == [2, 2]
    assert len(events) == 1 and events[0]["kind"] == "manual_window_acquired"
    assert json.loads(window.ACK_PATH.read_text())["request_id"] == paths["request_id"]
    monkeypatch.setattr(window.time, "time", lambda: 200)
    assert not window.hold_manual_window(30)


def test_ack_io_failure_does_not_resume_automation(paths, monkeypatch):
    window.REQUEST_PATH.write_text(json.dumps(paths), encoding="utf-8")
    monkeypatch.setattr(window, "ACK_PATH", window.ACK_PATH / "missing" / "ack.json")
    monkeypatch.setattr(window.time, "time", lambda: 150)
    monkeypatch.setattr(window.time, "sleep", lambda _: None)
    monkeypatch.setattr(window, "write_solver_heartbeat", lambda _: None)
    monkeypatch.setattr(window, "log_event", lambda _: None)
    assert window.hold_manual_window(2)


def test_loop_gate_precedes_startup_and_every_browser_control_action():
    from tools import pc2_solver_loop

    source = inspect.getsource(pc2_solver_loop.local_solver_loop)
    body = source[source.index("def local_solver_loop("):]
    assert body.index("while hold_manual_window(") < body.index("prepare_solver_browser(")
    loop = body[body.index("while True:"):]
    assert loop.index("if hold_manual_window(") < loop.index("process_pending_control_actions(")
    assert loop.index("if hold_manual_window(") < loop.index("compact_active_challenge_pages(")


@pytest.mark.parametrize("startup", [True, False])
def test_active_window_never_runs_browser_control_or_new_attempt(monkeypatch, startup):
    from tools import pc2_solver_loop as loop

    class StopLoop(BaseException):
        pass

    calls = []
    results = iter([True, True] if startup else [False, True])

    def gate(_poll):
        try:
            return next(results)
        except StopIteration:
            raise StopLoop from None

    monkeypatch.setattr(loop, "hold_manual_window", gate)
    monkeypatch.setattr(loop, "prepare_solver_browser", lambda *a: calls.append("prepare"))
    monkeypatch.setattr(loop, "IdlePointer", lambda *a: None)
    monkeypatch.setattr(loop, "process_pending_control_actions", lambda **kw: pytest.fail("control while held"))
    monkeypatch.setattr(loop, "run_solver_local_with_deadline", lambda *a, **kw: pytest.fail("input while held"))
    with pytest.raises(StopLoop):
        loop.local_solver_loop(poll_seconds=1)
    assert calls == ([] if startup else ["prepare"])

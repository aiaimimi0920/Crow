"""Retry policy runs without server imports, wall-clock waits or browser calls."""

import pytest

from src.auth_cookie_snapshot_retry import run_snapshot_retry


@pytest.fixture
def retry():
    states, sleeps, finalizations = [], [], []
    now = [100.0]

    def sleep(delay):
        sleeps.append(delay)
        now[0] += delay

    def finalize(completion_id, **kwargs):
        finalizations.append((completion_id, kwargs))
        return {"auth_state_confirmed": True}

    def run(results, **overrides):
        remaining = iter(results)

        def refresh(_payload):
            result = next(remaining)
            if isinstance(result, Exception):
                raise result
            return result

        dependencies = {
            "max_attempts": 3,
            "base_backoff": 200.0,
            "set_state": lambda **updates: states.append(updates),
            "refresh": refresh,
            "finalize": finalize,
            "clock": lambda: now[0],
            "sleep": sleep,
        }
        dependencies.update(overrides)
        run_snapshot_retry({"scope": "seed"}, "receipt", **dependencies)
        return states, sleeps, finalizations

    return run


def test_retry_caps_backoff_and_finalizes_only_healthy_snapshot(retry):
    states, sleeps, finalizations = retry(
        [RuntimeError("CDP reset"), None, {"refreshed": True}],
        finalize_auth=True,
        expected_challenge_id="challenge",
        completion_request={"scope": "seed"},
    )
    assert sleeps == [200.0, 300.0]
    assert [state["status"] for state in states] == [
        "running",
        "pending",
        "running",
        "pending",
        "running",
        "completed",
    ]
    assert states[1]["next_retry_at_epoch"] == 300.0
    assert states[1]["result"] == {
        "refreshed": False,
        "error": "RuntimeError('CDP reset')",
    }
    assert states[3]["next_retry_at_epoch"] == 600.0
    assert states[3]["result"]["reason"] == "invalid_refresh_result"
    assert states[-1]["last_finished_at_epoch"] == 600.0
    assert states[-1]["auth_state_confirmed"] is True
    assert finalizations == [
        (
            "receipt",
            {
                "expected_challenge_id": "challenge",
                "completion_request": {"scope": "seed"},
            },
        )
    ]


@pytest.mark.parametrize(
    "result,status",
    [
        ({"refreshed": False, "reason": "disabled_by_request"}, "skipped"),
        ({"refreshed": True}, "completed"),
        ({"refreshed": False}, "failed"),
    ],
)
def test_terminal_states_do_not_wait_or_finalize_without_request(retry, result, status):
    states, sleeps, finalizations = retry([result], max_attempts=1)
    assert states[-1]["status"] == status
    assert states[-1]["retry_queued"] is False
    assert not sleeps and not finalizations


@pytest.mark.parametrize("failure", [OSError, ValueError, RuntimeError])
def test_finalizer_error_records_terminal_state_and_preserves_exception(retry, failure):
    states = []
    original = failure("receipt write failed: private detail")

    def fail(*_args, **_kwargs):
        raise original

    with pytest.raises(failure) as raised:
        retry(
            [{"refreshed": True}],
            finalize_auth=True,
            finalize=fail,
            set_state=lambda **updates: states.append(updates),
        )
    assert raised.value is original
    assert [state["status"] for state in states] == ["running", "failed"]
    terminal = states[-1]
    assert terminal["refreshed"] is True
    assert terminal["auth_state_confirmed"] is False
    assert terminal["retry_queued"] is False
    assert terminal["next_retry_at_epoch"] is None
    assert terminal["last_finished_at_epoch"] == 100.0
    assert terminal["result"]["reason"] == "auth_finalization_failed"
    assert "private detail" not in str(terminal)


def test_failed_finalization_is_visible_and_same_receipt_can_be_rescheduled(
    monkeypatch,
):
    from src import server
    from src.runtime_state import RuntimeState

    runtime = RuntimeState()
    runtime.control.set_pause(True, "manual_required")
    monkeypatch.setattr(server, "RUNTIME", runtime)
    monkeypatch.setattr(server, "_auth_cookie_snapshot_retry_attempts", lambda: 1)
    refreshes = []
    monkeypatch.setattr(
        server,
        "_refresh_auth_cookie_snapshot",
        lambda _payload: refreshes.append(1) or {"refreshed": True},
    )

    def fail(*_args, **_kwargs):
        raise OSError("finalization failed")

    monkeypatch.setattr(server, "_finalize_auth_completion_after_cookie_snapshot", fail)
    with pytest.raises(OSError, match="finalization failed"):
        server._run_auth_cookie_snapshot_retry({}, "receipt", finalize_auth=True)
    failed = server._auth_cookie_snapshot_runtime_status()
    assert failed["status"] == "failed"
    assert failed["auth_state_confirmed"] is False
    assert runtime.control.snapshot().paused is True
    monkeypatch.setattr(
        server,
        "_finalize_auth_completion_after_cookie_snapshot",
        lambda *_args, **_kwargs: {"auth_state_confirmed": True},
    )
    scheduled = server._schedule_auth_cookie_snapshot_refresh(
        {}, "receipt", finalize_auth=True
    )
    assert scheduled["status"] == "pending"
    thread = runtime.cookie_snapshot.thread
    assert thread is not None
    thread.join(timeout=5)
    assert not thread.is_alive()
    recovered = server._auth_cookie_snapshot_runtime_status()
    assert recovered["status"] == "completed"
    assert recovered["auth_state_confirmed"] is True
    assert len(refreshes) == 2


@pytest.mark.parametrize("failure_stage", ["construct", "start"])
def test_snapshot_launch_failure_clears_pending_and_allows_retry(
    monkeypatch, failure_stage
):
    from types import SimpleNamespace

    from src import server
    from src.runtime_state import RuntimeState

    runtime = RuntimeState()
    runtime.control.set_pause(True, "manual_required")
    monkeypatch.setattr(server, "RUNTIME", runtime)
    error = RuntimeError("synthetic thread limit: private detail")

    def fail():
        raise error

    def thread_factory(**_kwargs):
        if failure_stage == "construct":
            raise error
        return SimpleNamespace(start=fail, is_alive=lambda: False)

    with monkeypatch.context() as launch:
        launch.setattr(server, "threading", SimpleNamespace(Thread=thread_factory))
        with pytest.raises(RuntimeError) as raised:
            server._schedule_auth_cookie_snapshot_refresh({}, "launch-receipt")
    assert raised.value is error
    failed = runtime.cookie_snapshot.snapshot()
    assert failed["status"] == "failed"
    assert failed["retry_queued"] is False
    assert failed["next_retry_at_epoch"] is None
    assert failed["auth_state_confirmed"] is False
    assert failed["result"]["reason"] == "snapshot_worker_start_failed"
    assert "private detail" not in str(failed)
    assert runtime.cookie_snapshot.thread is None
    assert runtime.control.snapshot().paused is True

    def complete(*_args, **_kwargs):
        runtime.cookie_snapshot.update({"status": "completed", "refreshed": True})

    monkeypatch.setattr(server, "_run_auth_cookie_snapshot_retry", complete)
    assert (
        server._schedule_auth_cookie_snapshot_refresh({}, "launch-receipt")["status"]
        == "pending"
    )
    thread = runtime.cookie_snapshot.thread
    assert thread is not None
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert runtime.cookie_snapshot.snapshot()["status"] == "completed"

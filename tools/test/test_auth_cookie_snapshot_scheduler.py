"""Single-flight scheduling and request ownership across real worker threads."""

import threading

import pytest

from src.auth_cookie_snapshot_scheduler import schedule_refresh
from src.runtime_state import RuntimeState


def test_disabled_idle_snapshot_does_not_start_work():
    runtime = RuntimeState()

    def unexpected(*args, **kwargs):
        pytest.fail("disabled refresh must not invoke scheduling effects")

    result = schedule_refresh(
        {},
        "disabled-receipt",
        state=runtime.cookie_snapshot,
        retry_attempts=unexpected,
        run_retry=unexpected,
        clock=unexpected,
        thread_factory=unexpected,
        refresh_enabled=False,
    )

    assert result["status"] == "skipped"
    assert result["completion_id"] == "disabled-receipt"
    assert result["result"]["reason"] == "disabled_by_request"
    assert runtime.cookie_snapshot.snapshot() == result
    assert runtime.cookie_snapshot.thread is None


@pytest.mark.parametrize("entrypoint", ["native", "facade"])
@pytest.mark.parametrize("second_refresh", [True, False])
def test_snapshot_scheduler_keeps_one_worker_and_copies_requests(
    monkeypatch, entrypoint, second_refresh
):
    runtime = RuntimeState()
    started, release = threading.Event(), threading.Event()
    received, attempts = [], []

    def retry_attempts():
        attempts.append(1)
        return 3

    def worker(payload, completion_id, **options):
        received.append((payload, completion_id, options))
        started.set()
        assert release.wait(5)
        runtime.cookie_snapshot.update({"status": "completed", "refreshed": True})

    if entrypoint == "facade":
        from src import server

        monkeypatch.setattr(server, "RUNTIME", runtime)
        monkeypatch.setattr(server, "_run_auth_cookie_snapshot_retry", worker)
        monkeypatch.setattr(
            server, "_auth_cookie_snapshot_retry_attempts", retry_attempts
        )
        schedule = server._schedule_auth_cookie_snapshot_refresh
    else:

        def schedule(payload, completion_id, **kwargs):
            return schedule_refresh(
                payload,
                completion_id,
                state=runtime.cookie_snapshot,
                retry_attempts=retry_attempts,
                run_retry=worker,
                clock=lambda: 100.0,
                thread_factory=threading.Thread,
                refresh_enabled=payload.get("refresh_cookie_snapshot", True),
                **kwargs,
            )

    payload = {"source": "operator"}
    request = {"scope": "seed"}
    first = schedule(
        payload,
        "receipt",
        finalize_auth=True,
        expected_challenge_id="challenge",
        completion_request=request,
    )
    thread = runtime.cookie_snapshot.thread
    assert thread is not None
    try:
        assert started.wait(5)
        second = schedule(
            {"refresh_cookie_snapshot": second_refresh}, "another-receipt"
        )
        assert runtime.cookie_snapshot.snapshot()["completion_id"] == "receipt"
        assert runtime.cookie_snapshot.snapshot()["status"] == "pending"
        assert first["status"] == "pending"
        assert second["reason"] == "refresh_already_running"
        assert second["completion_id"] == "receipt"
        assert runtime.cookie_snapshot.thread is thread
        assert "reason" not in runtime.cookie_snapshot.snapshot()
        payload["source"] = "changed"
        request["scope"] = "detail"
        assert received == [
            (
                {"source": "operator"},
                "receipt",
                {
                    "finalize_auth": True,
                    "expected_challenge_id": "challenge",
                    "completion_request": {"scope": "seed"},
                },
            )
        ]
        assert attempts == [1]
    finally:
        release.set()
        thread.join(timeout=5)
    assert not thread.is_alive()
    reused = schedule({}, "receipt")
    assert reused["status"] == "completed"
    assert attempts == [1]
    assert len(received) == 1

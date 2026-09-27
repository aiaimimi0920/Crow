"""Retry polling uses live policy and cadence, including after a failed attempt."""

import logging
from types import SimpleNamespace

import pytest

from src.solver_retry_loop import SolverRetryLoop


class EndPoll(BaseException):
    """Stop after one iteration without invoking the retry error handler."""


@pytest.mark.parametrize("facade", [False, True])
@pytest.mark.parametrize(
    "outcome", ["queued", "invalid_request", "inactive", "failure"]
)
def test_saved_retry_loop_reads_current_policy_and_poll(
    monkeypatch, caplog, facade, outcome
):
    from src import server, server_collection_operations

    host = server if facade else server_collection_operations
    run = host.manual_solver_retry_thread
    assert isinstance(run.__self__, SolverRetryLoop)
    if facade:
        assert server._CONTEXT.manual_solver_retry_thread is run
    caplog.set_level(logging.INFO)
    attempts = []
    delays = []

    def trigger():
        attempts.append(outcome)
        if outcome == "failure":
            raise OSError("isolated retry failure")
        return {
            "queued": outcome != "inactive",
            "attempt": 1,
            "solver_request": {"target_url": "https://example.test"}
            if outcome == "queued"
            else None,
        }

    def sleep(seconds):
        delays.append(seconds)
        raise EndPoll

    monkeypatch.setattr(
        host, "_trigger_manual_solver_retry_if_due", trigger, raising=False
    )
    monkeypatch.setattr(host, "time", SimpleNamespace(sleep=sleep))
    for interval in (2, 7):
        monkeypatch.setattr(
            host,
            "_manual_solver_retry_poll_seconds",
            lambda interval=interval: interval,
            raising=False,
        )
        with pytest.raises(EndPoll):
            run()
    assert attempts == [outcome, outcome]
    assert delays == [2, 7]
    if outcome == "failure":
        assert "isolated retry failure" in caplog.text
    elif outcome != "inactive":
        assert "Manual-required solver retry queued attempt=1 target=" in caplog.text
    else:
        assert "retry queued" not in caplog.text

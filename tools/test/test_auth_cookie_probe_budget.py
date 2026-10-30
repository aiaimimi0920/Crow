"""Detail HTTP slots are owned by a retry job, not shared runtime state."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from types import SimpleNamespace

import pytest

from src.auth_cookie_probe_budget import (
    current_detail_probe_budget,
    snapshot_probe_budget,
)
from src.auth_cookie_snapshot_retry import run_snapshot_retry


@pytest.fixture
def job():
    state = SimpleNamespace(rows=[], waits=[], finalized=0)

    def finalize(*_args, **_kwargs):
        assert current_detail_probe_budget() is None
        state.finalized += 1
        return {"auth_state_confirmed": True}

    def run(refresh, **options):
        values = {
            "max_attempts": 3,
            "base_backoff": 2,
            "set_state": lambda **row: state.rows.append(row),
            "refresh": refresh,
            "finalize": finalize,
            "clock": lambda: 100.0,
            "sleep": state.waits.append,
            "finalize_auth": True,
            "completion_request": {"scope": "detail"},
        }
        scope = options.pop("scope", "detail")
        values.update(options)
        run_snapshot_retry({"scope": scope}, "synthetic-completion", **values)
        assert current_detail_probe_budget() is None
        return state

    state.run = run
    return state


def test_two_then_one_slots_preserve_backoff_and_report_exhaustion(job):
    rounds = []

    def refresh(_payload):
        budget = current_detail_probe_budget()
        rounds.append(budget)
        budget.consume()
        if len(rounds) == 1:
            budget.consume()
        else:
            assert not budget.available
        return {"refreshed": False}

    state = job.run(refresh)
    assert rounds[0] is rounds[1] and rounds[0].used == 3
    assert state.waits == [2] and not state.finalized
    assert state.rows[-1]["status"] == "failed"
    assert state.rows[-1]["attempts"] == 3
    assert [row["attempts"] for row in state.rows if row["status"] == "running"] == [
        1,
        3,
    ]


def test_one_then_two_slots_can_finalize_without_losing_last_slot(job):
    count = [0]

    def refresh(_payload):
        count[0] += 1
        budget = current_detail_probe_budget()
        budget.consume()
        if count[0] == 2:
            budget.consume()
        return {"refreshed": count[0] == 2}

    state = job.run(refresh)
    assert state.finalized == 1 and state.waits == [2]
    assert state.rows[-1]["status"] == "completed"
    assert state.rows[-1]["attempts"] == 3


@pytest.mark.parametrize("raises", [False, True])
def test_zero_http_configuration_or_mock_failures_still_terminate(job, raises):
    calls = []

    def refresh(_payload):
        calls.append(current_detail_probe_budget())
        if raises:
            raise ValueError("synthetic configuration error")
        return {"refreshed": False}

    state = job.run(refresh)
    assert len(calls) == 3 and calls[0].used == 0
    assert state.rows[-1]["attempts"] == 3 and state.waits == [2, 4]


def test_exception_after_http_consume_cannot_borrow_retry_slots(job):
    calls = []

    def refresh(_payload):
        budget = current_detail_probe_budget()
        budget.consume()
        if not calls:
            budget.consume()
        calls.append(budget.used)
        raise OSError("synthetic transport failure")

    state = job.run(refresh)
    assert calls == [2, 3]
    assert state.rows[-1]["attempts"] == 3 and state.waits == [2]


@pytest.mark.parametrize("scope", ["detail", " Detail ", "DETAIL"])
def test_explicit_detail_scope_normalization_matches_production(job, scope):
    seen = []

    def refresh(_payload):
        seen.append(current_detail_probe_budget())
        return {"refreshed": True}

    job.run(refresh, scope=scope)
    assert seen[0] is not None


@pytest.mark.parametrize("scope", [None, "seed", "unknown"])
def test_other_or_legacy_scope_cannot_borrow_completion_request_hint(job, scope):
    def refresh(_payload):
        assert current_detail_probe_budget() is None
        return {"refreshed": True}

    assert job.run(refresh, scope=scope).finalized == 1


def test_mock_round_reduces_effective_remaining_transport_slots(job):
    count = [0]

    def refresh(_payload):
        count[0] += 1
        budget = current_detail_probe_budget()
        if count[0] == 1:
            return {"refreshed": False}
        budget.consume()
        budget.consume()
        assert not budget.available
        return {"refreshed": False}

    state = job.run(refresh)
    assert count[0] == 2 and state.rows[-1]["attempts"] == 3


@pytest.mark.parametrize("exit_kind", ["cancel", "finalizer", "state_writer"])
def test_every_exception_exit_resets_context(job, exit_kind):
    class Cancelled(BaseException):
        pass

    def refresh(_payload):
        if exit_kind == "cancel":
            raise Cancelled()
        return {"refreshed": True}

    def fail(*_args, **_kwargs):
        raise ValueError("synthetic effect failure")

    options = {"finalize": fail} if exit_kind == "finalizer" else {}
    if exit_kind == "state_writer":
        options["set_state"] = fail
    with pytest.raises(Cancelled if exit_kind == "cancel" else ValueError):
        job.run(refresh, **options)
    assert current_detail_probe_budget() is None
    if exit_kind == "finalizer":
        assert job.rows[-1]["status"] == "failed"
        assert job.rows[-1]["result"]["reason"] == "auth_finalization_failed"


def test_stopping_budget_rejects_transport_before_consumption():
    stop = Event()
    with snapshot_probe_budget("detail", 3, stop) as budget:
        stop.set()
        with pytest.raises(RuntimeError, match="budget unavailable"):
            budget.consume()
        assert budget.used == 0
    assert current_detail_probe_budget() is None


def test_two_worker_threads_and_consecutive_jobs_do_not_share_mutable_budget():
    barrier = Barrier(2)

    def worker(limit):
        assert current_detail_probe_budget() is None
        with snapshot_probe_budget("detail", limit, None) as budget:
            barrier.wait(timeout=10)
            budget.consume()
            result = budget
        assert current_detail_probe_budget() is None
        with snapshot_probe_budget("detail", limit, None) as fresh:
            assert fresh is not result and fresh.used == 0
        return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = list(pool.map(worker, (2, 3)))
    assert a is not b and a.used == b.used == 1
    assert current_detail_probe_budget() is None

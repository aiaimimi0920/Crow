"""Recovery polling respects the report floor, cancellation and one deadline."""

import math
from types import SimpleNamespace

import pytest

from tools import detail_worker_wait as owner


@pytest.fixture
def clock(monkeypatch):
    state = SimpleNamespace(now=0.0, waits=[], timeouts=[], stopping=False)

    def wait(seconds):
        state.waits.append(seconds)
        state.now += seconds

    def fetch(_url, *, timeout):
        state.timeouts.append(timeout)
        return {
            "paused": False,
            "collection_scopes": {
                "detail": {
                    "paused": False,
                    "manual_required": False,
                    "challenge_id": None,
                }
            },
        }

    monkeypatch.setattr(owner.time, "monotonic", lambda: state.now)
    monkeypatch.setattr(owner.worker_lifecycle, "wait", wait)
    monkeypatch.setattr(
        owner.worker_lifecycle, "checkpoint", lambda _: not state.stopping
    )
    monkeypatch.setattr(owner, "fetch_json", fetch)
    return state


def run_wait(seconds=900, *, floor=0):
    item = {"reason": "detail_challenge_page"}
    if floor:
        item.update(
            reason="detail_stale_challenge_ignored",
            captcha_solver_report={
                "status": "recent_auth_complete",
                "scope": "detail",
                "retry_after_seconds": floor,
            },
        )
    return owner.wait_after_detail_batch(
        SimpleNamespace(analysis_only=False, api_base_url="https://nas.invalid/api"),
        {"results": [item]},
        seconds,
    )


@pytest.mark.parametrize("floor", [40, 43, 142, 142.2, 899])
def test_clear_detail_wakes_at_rounded_report_floor_without_extra_polls(clock, floor):
    receipt = run_wait(floor=floor)
    assert clock.now == math.ceil(floor)
    assert len(clock.timeouts) == 1
    assert receipt["wait_exit"] == "report_backoff_elapsed"
    assert max(clock.waits) <= 30


def test_challenge_never_starts_status_poll_at_deadline(clock, monkeypatch):
    def fetch(_url, *, timeout):
        clock.timeouts.append(timeout)
        return {}

    monkeypatch.setattr(owner, "fetch_json", fetch)
    receipt = run_wait(90)
    assert clock.now == 90
    assert clock.timeouts == [5, 5]
    assert receipt["wait_exit"] == "deadline_elapsed"


def test_final_status_timeout_is_bounded_by_remaining_wait(clock, monkeypatch):
    def fetch(_url, *, timeout):
        clock.timeouts.append(timeout)
        return {}

    monkeypatch.setattr(owner, "fetch_json", fetch)
    receipt = run_wait(32)
    assert clock.timeouts == [2]
    assert clock.now == 32
    assert receipt["wait_exit"] == "deadline_elapsed"


def test_stop_during_status_read_cannot_be_reported_as_recovery(clock, monkeypatch):
    original = owner.fetch_json

    def fetch(*args, **kwargs):
        status = original(*args, **kwargs)
        clock.stopping = True
        return status

    monkeypatch.setattr(owner, "fetch_json", fetch)
    receipt = run_wait()
    assert clock.now == 30
    assert receipt["wait_exit"] == "stopping"


def test_status_returning_after_deadline_is_not_fresh_recovery(clock, monkeypatch):
    original = owner.fetch_json

    def fetch(*args, **kwargs):
        status = original(*args, **kwargs)
        clock.now += kwargs["timeout"]
        return status

    monkeypatch.setattr(owner, "fetch_json", fetch)
    receipt = run_wait(32)
    assert clock.now == 32
    assert receipt["wait_exit"] == "deadline_elapsed"


def test_floor_equal_to_deadline_requires_no_final_status_request(clock):
    receipt = run_wait(142, floor=142)
    assert clock.now == 142
    assert clock.timeouts == []
    assert receipt["wait_exit"] == "deadline_elapsed"


def test_late_cdp_metadata_is_not_accepted_as_recovery(clock, monkeypatch):
    def probe(_endpoint, *, timeout_seconds):
        clock.now += timeout_seconds
        return True

    monkeypatch.setattr(owner, "cdp_metadata_recovered", probe)
    result = {
        "results": [
            {
                "decision": "detail_item_retryable_failure",
                "reason": "detail_cdp_unreachable",
                "capture_failure": {
                    "operation": "connect_over_cdp_bounded_reconnect",
                    "cause": {
                        "type": "RuntimeError",
                        "message": "runtime_error",
                        "endpoint_unhealthy": True,
                    },
                },
            }
        ]
    }
    receipt = owner.wait_after_detail_batch(
        SimpleNamespace(
            analysis_only=False,
            api_base_url="https://nas.invalid/api",
            cdp_endpoint="http://cdp.invalid:9224",
        ),
        result,
        32,
    )
    assert clock.now == 32
    assert receipt["cdp_poll_count"] == 1
    assert receipt["wait_exit"] == "deadline_elapsed"

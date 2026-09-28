"""Auth recovery must wake sleeping capture workers without bypassing other backoffs."""

from types import SimpleNamespace

import pytest

from tools import detail_worker_wait as owner


@pytest.fixture
def clock(monkeypatch):
    state = {"now": 0, "waits": [], "requests": 0}

    def wait(seconds):
        state["waits"].append(seconds)
        state["now"] += seconds

    monkeypatch.setattr(owner.time, "monotonic", lambda: state["now"])
    monkeypatch.setattr(owner.worker_lifecycle, "wait", wait)
    monkeypatch.setattr(owner.worker_lifecycle, "checkpoint", lambda _: True)
    return state


def run(monkeypatch, clock, status, *, analysis=False, reason="detail_challenge_page"):
    def fetch(*args, **kwargs):
        clock["requests"] += 1
        if isinstance(status, Exception):
            raise status
        return status

    monkeypatch.setattr(owner, "fetch_json", fetch)
    config = SimpleNamespace(analysis_only=analysis, api_base_url="https://nas/api")
    owner.wait_after_detail_batch(config, {"results": [{"reason": reason}]}, 900)


def resumed():
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


def test_confirmed_recovery_wakes_worker_within_one_poll(monkeypatch, clock):
    run(monkeypatch, clock, resumed())
    assert clock["now"] == 30
    assert clock["requests"] == 1


@pytest.mark.parametrize(
    "status",
    [
        {},
        OSError("offline"),
        {"paused": False},
        {"paused": True, "collection_scopes": resumed()["collection_scopes"]},
        {
            "paused": False,
            "collection_scopes": {
                "detail": {
                    "paused": False,
                    "manual_required": True,
                    "challenge_id": None,
                }
            },
        },
        {
            "paused": False,
            "collection_scopes": {
                "detail": {
                    "paused": False,
                    "manual_required": False,
                    "challenge_id": "new-challenge",
                }
            },
        },
    ],
)
def test_unknown_or_still_blocked_state_keeps_backoff(monkeypatch, clock, status):
    run(monkeypatch, clock, status)
    assert clock["now"] == 900


@pytest.mark.parametrize(
    "analysis,reason",
    [
        (True, "detail_challenge_page"),
        (False, "detail_cdp_unreachable"),
        (False, "network_error"),
    ],
)
def test_unrelated_backoffs_do_not_probe_or_wake(monkeypatch, clock, analysis, reason):
    run(monkeypatch, clock, resumed(), analysis=analysis, reason=reason)
    assert clock["waits"] == [900]
    assert clock["requests"] == 0


def test_shutdown_during_wait_does_not_probe(monkeypatch, clock):
    monkeypatch.setattr(
        owner.worker_lifecycle, "checkpoint", lambda _: clock["now"] == 0
    )
    run(monkeypatch, clock, resumed())
    assert clock["now"] == 30
    assert clock["requests"] == 0

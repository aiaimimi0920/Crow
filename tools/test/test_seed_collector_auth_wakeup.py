"""Seed recovery wakes only a challenge backoff with a confirmed clear scope."""

from types import SimpleNamespace

import pytest

from tools import seed_collector_wait as owner


@pytest.fixture
def clock(monkeypatch):
    state = {"now": 0, "waits": [], "polls": 0}

    def wait(seconds):
        state["waits"].append(seconds)
        state["now"] += seconds

    monkeypatch.setattr(owner.time, "monotonic", lambda: state["now"])
    monkeypatch.setattr(owner.worker_lifecycle, "checkpoint", lambda _: True)
    monkeypatch.setattr(owner.worker_lifecycle, "wait", wait)
    return state


def clear_status():
    return {
        "paused": False,
        "collection_scopes": {
            "seed": {
                "paused": False,
                "manual_required": False,
                "challenge_id": None,
            }
        },
    }


def run(
    monkeypatch, clock, status, results=None, *, seconds=900, api="https://nas/api"
):
    def fetch(*args, **kwargs):
        clock["polls"] += 1
        if isinstance(status, Exception):
            raise status
        return status

    monkeypatch.setattr(owner, "fetch_json", fetch)
    owner.wait_after_seed_run(
        SimpleNamespace(api_base_url=api),
        results if results is not None else [{"reason": "list_challenge_page"}],
        seconds,
    )


@pytest.mark.parametrize("detail_only", [False, True])
def test_confirmed_recovery_wakes_within_one_poll(monkeypatch, clock, detail_only):
    status = clear_status()
    if detail_only:
        status["paused"] = True
        status["collection_scopes"]["detail"] = {"paused": True}
    run(monkeypatch, clock, status)
    assert clock == {"now": 30, "waits": [30], "polls": 1}


@pytest.mark.parametrize(
    "status",
    [
        {},
        [],
        OSError("offline"),
        {"paused": False},
        {"paused": True, "collection_scopes": clear_status()["collection_scopes"]},
        {"paused": False, "collection_scopes": {"seed": {"paused": True}}},
        {
            "paused": False,
            "collection_scopes": {"seed": {"paused": False, "manual_required": True}},
        },
        {
            "paused": False,
            "collection_scopes": {
                "seed": {
                    "paused": False,
                    "manual_required": False,
                    "challenge_id": "still-active",
                }
            },
        },
    ],
)
def test_unknown_or_blocked_status_keeps_backoff(monkeypatch, clock, status):
    run(monkeypatch, clock, status)
    assert clock["now"] == 900


@pytest.mark.parametrize(
    "results",
    [
        [{"reason": "network_error"}],
        [{"decision": "seed_scan_queue_empty"}],
        [{"decision": "seed_page_collected", "auth_probe": {"attempted": True}}],
    ],
)
def test_non_challenge_backoff_is_unchanged(monkeypatch, clock, results):
    run(monkeypatch, clock, clear_status(), results)
    assert clock == {"now": 900, "waits": [900], "polls": 0}


@pytest.mark.parametrize("api,seconds", [("", 900), ("https://nas/api", 30)])
def test_disabled_or_short_wait_does_not_poll(monkeypatch, clock, api, seconds):
    run(monkeypatch, clock, clear_status(), api=api, seconds=seconds)
    assert clock["waits"] == [seconds]
    assert clock["polls"] == 0


def test_shutdown_during_wait_does_not_probe(monkeypatch, clock):
    monkeypatch.setattr(
        owner.worker_lifecycle, "checkpoint", lambda _: clock["now"] == 0
    )
    run(monkeypatch, clock, clear_status())
    assert clock == {"now": 30, "waits": [30], "polls": 0}

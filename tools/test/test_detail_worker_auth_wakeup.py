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


def run(
    monkeypatch,
    clock,
    status,
    *,
    analysis=False,
    reason="detail_challenge_page",
    layout="top",
):
    if layout != "top" and isinstance(status, dict) and "collection_scopes" in status:
        status = dict(status)
        status["captcha_solver"] = {layout: status.pop("collection_scopes")}

    def fetch(*args, **kwargs):
        clock["requests"] += 1
        if isinstance(status, Exception):
            raise status
        return status

    monkeypatch.setattr(owner, "fetch_json", fetch)
    config = SimpleNamespace(analysis_only=analysis, api_base_url="https://nas/api")
    return owner.wait_after_detail_batch(config, {"results": [{"reason": reason}]}, 900)


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


@pytest.mark.parametrize("layout", ["top", "collection_scopes", "scopes"])
def test_confirmed_recovery_wakes_worker_within_one_poll(monkeypatch, clock, layout):
    receipt = run(monkeypatch, clock, resumed(), layout=layout)
    assert clock["now"] == 30
    assert clock["requests"] == 1
    assert receipt == {
        "requested_wait_seconds": 900,
        "actual_wait_seconds": 30,
        "status_poll_count": 1,
        "wait_exit": "detail_resumed",
    }


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
@pytest.mark.parametrize("layout", ["top", "collection_scopes", "scopes"])
def test_unknown_or_still_blocked_state_keeps_backoff(
    monkeypatch, clock, status, layout
):
    receipt = run(monkeypatch, clock, status, layout=layout)
    assert clock["now"] == 900
    assert receipt["wait_exit"] == "deadline_elapsed"
    assert receipt["status_poll_count"] == clock["requests"] == 30


@pytest.mark.parametrize(
    "analysis,reason",
    [
        (True, "detail_challenge_page"),
        (False, "detail_cdp_unreachable"),
        (False, "network_error"),
    ],
)
def test_unrelated_backoffs_do_not_probe_or_wake(monkeypatch, clock, analysis, reason):
    receipt = run(monkeypatch, clock, resumed(), analysis=analysis, reason=reason)
    assert clock["waits"] == [900]
    assert clock["requests"] == 0
    assert receipt["wait_exit"] == "wait_returned"
    assert receipt["actual_wait_seconds"] == 900


def test_shutdown_during_wait_does_not_probe(monkeypatch, clock):
    monkeypatch.setattr(
        owner.worker_lifecycle, "checkpoint", lambda _: clock["now"] == 0
    )
    receipt = run(monkeypatch, clock, resumed())
    assert clock["now"] == 30
    assert clock["requests"] == 0
    assert receipt["wait_exit"] == "stopping"


def test_already_stopping_has_no_wait_or_probe(monkeypatch, clock):
    monkeypatch.setattr(owner.worker_lifecycle, "checkpoint", lambda _: False)
    receipt = run(monkeypatch, clock, resumed())
    assert clock["waits"] == []
    assert clock["requests"] == 0
    assert receipt["actual_wait_seconds"] == 0
    assert receipt["wait_exit"] == "stopping"


def test_actual_wait_includes_status_request_time(monkeypatch, clock):
    def fetch(*_args, **_kwargs):
        clock["now"] += 4
        return resumed()

    monkeypatch.setattr(owner, "fetch_json", fetch)
    receipt = owner.wait_after_detail_batch(
        SimpleNamespace(analysis_only=False, api_base_url="https://nas/api"),
        {"results": [{"decision": "detail_collection_paused"}]},
        900,
    )
    assert receipt["actual_wait_seconds"] == 34
    assert receipt["status_poll_count"] == 1


@pytest.mark.parametrize("authoritative", [{}, {"detail": {"paused": True}}])
@pytest.mark.parametrize("layout", ["collection_scopes", "scopes"])
def test_top_level_scope_state_is_not_overridden_by_nested_clear(
    monkeypatch, clock, authoritative, layout
):
    status = {
        "paused": False,
        "collection_scopes": authoritative,
        "captcha_solver": {layout: resumed()["collection_scopes"]},
    }
    run(monkeypatch, clock, status)
    assert clock["now"] == 900

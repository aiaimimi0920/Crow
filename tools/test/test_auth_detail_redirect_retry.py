"""A same-item redirect must spend existing retry slots, not bypass auth proof."""

import json
from threading import Event
from types import SimpleNamespace

import pytest
from requests import ReadTimeout

from src import auth_cookie_health as health
from src.auth_cookie_snapshot_retry import run_snapshot_retry

TARGET = "https://sf-item.taobao.com/sf_item/123.htm"
ALIAS = "https://susong-item.taobao.com/auction/123.htm"
READY = '<div id="J_StartPrice">100</div>'


def run_detail(
    monkeypatch,
    *,
    limit=3,
    destination=ALIAS,
    final_status=200,
    fail_on_url=None,
    stop_event=None,
):
    calls, states, finalized, sessions = [], [], [], []

    def factory(_cookies):
        session = SimpleNamespace(closed=False)

        def get(url, **options):
            assert not session.closed and options["allow_redirects"] is False
            calls.append((url, options))
            if fail_on_url == url:
                raise ReadTimeout("cookie2=synthetic-private-value")
            if stop_event is not None:
                stop_event.set()
            return SimpleNamespace(
                url=url,
                status_code=302 if url == TARGET else final_status,
                text=READY,
                headers={"Location": destination},
            )

        session.get = get
        session.close = lambda: setattr(session, "closed", True)
        sessions.append(session)
        return session

    monkeypatch.setattr(health, "build_session_from_playwright_cookies", factory)
    monkeypatch.setattr(health, "resolve_cdp_user_agent", lambda _: "synthetic-UA")

    def refresh(_payload):
        result = health.probe_cookie_snapshot_health([], [], detail_target_url=TARGET)
        return {"refreshed": result["scope_healthy"], "health": result}

    def finalize(*_args, **_kwargs):
        finalized.append(True)
        return {"auth_state_confirmed": True}

    run_snapshot_retry(
        {"scope": "detail"},
        "synthetic-completion",
        max_attempts=limit,
        base_backoff=0,
        set_state=lambda **row: states.append(row),
        refresh=refresh,
        finalize=finalize,
        clock=lambda: 100.0,
        sleep=lambda _: None,
        finalize_auth=True,
        expected_challenge_id="synthetic-challenge",
        completion_request={"scope": "detail"},
        stop_event=stop_event,
    )
    assert all(session.closed for session in sessions)
    return calls, states, finalized


def test_same_item_alias_can_reach_real_payload_within_original_retry_budget(
    monkeypatch,
):
    calls, states, finalized = run_detail(monkeypatch)
    assert states[-1]["status"] == "completed"
    assert states[-1]["auth_state_confirmed"] is True
    assert states[-1]["attempts"] == 2
    assert [url for url, _ in calls] == [TARGET, ALIAS]
    assert finalized == [True]
    assert states[-1]["result"]["health"]["healthy"] is False


@pytest.mark.parametrize("limit", [1, 2, 3, 4])
def test_failed_redirects_never_expand_the_original_http_request_budget(
    monkeypatch, limit
):
    calls, states, finalized = run_detail(monkeypatch, limit=limit, final_status=403)
    assert len(calls) == limit
    assert states[-1]["status"] == "failed"
    assert states[-1]["attempts"] == states[-1]["max_attempts"] == limit
    assert not finalized


@pytest.mark.parametrize(
    "destination",
    [ALIAS + "?trace=synthetic-secret", "https://login.taobao.com/", TARGET],
)
def test_rejected_redirect_uses_original_retries_without_finalizing(
    monkeypatch, destination
):
    calls, states, finalized = run_detail(monkeypatch, destination=destination)
    assert [url for url, _ in calls] == [TARGET] * 3
    assert states[-1]["status"] == "failed" and not finalized


@pytest.mark.parametrize("failed_url", [TARGET, ALIAS])
def test_real_health_transport_exception_consumes_slot_and_redacts_error(
    monkeypatch, failed_url
):
    calls, states, finalized = run_detail(monkeypatch, fail_on_url=failed_url)
    assert len(calls) == 3 and not finalized
    assert states[-1]["status"] == "failed" and states[-1]["attempts"] == 3
    assert "synthetic-private-value" not in json.dumps(states)
    assert any(
        row.get("result", {})
        .get("health", {})
        .get("sample_results", [{}])[0]
        .get("error")
        == "ReadTimeout"
        for row in states
    )


def test_real_retry_stop_between_hops_never_finalizes_or_sends_second_get(
    monkeypatch,
):
    stop = Event()
    calls, states, finalized = run_detail(monkeypatch, stop_event=stop)
    assert len(calls) == 1 and not finalized
    assert states[-1]["status"] == "failed"
    assert states[-1]["result"] == {"reason": "application_stopping"}

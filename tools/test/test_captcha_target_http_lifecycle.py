"""CDP HTTP errors must not create fictitious targets or successful cleanup."""

from types import SimpleNamespace

import pytest
import requests

from src.captcha_budget import SolveBudget, SolveStopped
from src.captcha_solver import CaptchaSolver

PAGE = {
    "id": "owned",
    "type": "page",
    "url": "https://fixture.local/challenge",
    "webSocketDebuggerUrl": "ws://fixture/owned",
}


def response(payload, status=200):
    return SimpleNamespace(status_code=status, json=lambda: payload)


def stub_put(monkeypatch, reply):
    attempts = []

    def put(_url, *, timeout):
        attempts.append(timeout)
        return reply

    monkeypatch.setattr("src.captcha_cdp.requests.put", put)
    return attempts


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_create_rejects_non_success_even_with_page_body(monkeypatch, status):
    attempts = stub_put(monkeypatch, response(PAGE, status))
    solver = CaptchaSolver(target_url=PAGE["url"])
    assert solver._open_target_tab() is None
    assert attempts == [5, 8, 12]
    assert solver._opened_target_ids == set()
    assert solver.target_id is None


@pytest.mark.parametrize(
    "payload",
    [
        {"error": "private-body"},
        [],
        None,
        False,
        {**PAGE, "id": ""},
        {**PAGE, "id": 123},
        {**PAGE, "type": "service_worker"},
    ],
)
def test_create_rejects_invalid_page_metadata(monkeypatch, payload, caplog):
    stub_put(monkeypatch, response(payload))
    solver = CaptchaSolver(target_url=PAGE["url"])
    assert solver._open_target_tab() is None
    assert solver.target_id is None
    assert solver._opened_target_ids == set()
    assert "private-body" not in caplog.text


@pytest.mark.parametrize("socket", [None, "", 123, "http://fixture/owned"])
def test_incomplete_created_target_never_opens_another_page(monkeypatch, socket):
    attempts = stub_put(monkeypatch, response({**PAGE, "webSocketDebuggerUrl": socket}))
    solver = CaptchaSolver(target_url=PAGE["url"])
    assert solver._open_target_tab() is None
    assert attempts == [5]
    assert solver._opened_target_ids == {"owned"}
    assert solver.target_id is None


def test_transient_create_failure_preserves_existing_retry_limit(monkeypatch):
    replies = iter([response({"error": "private-body"}, 503), response(PAGE)])
    attempts = []

    def put(_url, *, timeout):
        attempts.append(timeout)
        return next(replies)

    monkeypatch.setattr("src.captcha_cdp.requests.put", put)
    solver = CaptchaSolver(target_url=PAGE["url"])
    assert solver._open_target_tab() is PAGE
    assert attempts == [5, 8]
    assert solver._opened_target_ids == {"owned"}


def test_create_http_retry_still_obeys_cancellation(monkeypatch):
    attempts = stub_put(monkeypatch, response(PAGE, 503))
    solver = CaptchaSolver(
        target_url=PAGE["url"], cancel_checker=lambda: bool(attempts)
    )
    solver._solve_budget = SolveBudget()
    with pytest.raises(SolveStopped):
        solver._open_target_tab()
    assert attempts == [5]


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500, 503])
def test_close_http_failure_is_not_success(monkeypatch, status, caplog):
    calls = []

    def get(url, *, timeout):
        calls.append((url, timeout))
        return response({"error": "private-body"}, status)

    monkeypatch.setattr("src.captcha_target.requests.get", get)
    assert CaptchaSolver()._close_cdp_target("owned/target") is False
    assert calls == [("http://localhost:9222/json/close/owned%2Ftarget", 5)]
    assert "private-body" not in caplog.text
    assert str(status) in caplog.text


def test_close_success_does_not_parse_non_json_chromium_reply(monkeypatch):
    def no_json():
        pytest.fail("Chromium close reply is plain text")

    monkeypatch.setattr(
        "src.captcha_target.requests.get",
        lambda *_a, **_k: SimpleNamespace(status_code=200, json=no_json),
    )
    assert CaptchaSolver()._close_cdp_target("owned") is True


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_failed_keepalive_creation_does_not_fake_preserved_page(monkeypatch, status):
    attempts = stub_put(monkeypatch, response({"id": "not-created"}, status))
    solver = CaptchaSolver()
    solver._opened_target_ids.update({"owned", "second"})
    closed = []
    monkeypatch.setattr(
        solver, "_close_cdp_target", lambda key: closed.append(key) or True
    )
    monkeypatch.setattr(solver, "_page_target_limit", lambda: 2)
    summary = solver._compact_cdp_pages_if_needed([PAGE, {**PAGE, "id": "second"}])
    assert summary == {
        "triggered": True,
        "page_count": 2,
        "closed": 1,
        "preserved_target_id": "owned",
    }
    assert closed == ["second"]
    assert attempts == [5]


@pytest.mark.parametrize("current_succeeds", [False, True])
def test_cleanup_only_forgets_successfully_closed_owned_targets(
    monkeypatch, current_succeeds
):
    solver = CaptchaSolver()
    solver._remember_target_tab(PAGE)
    solver._opened_target_ids.update({"owned", "other"})
    monkeypatch.setattr(
        solver, "_close_cdp_target", lambda key: (key == "owned") is current_succeeds
    )
    assert solver._close_owned_target_tabs() == 1
    assert solver._opened_target_ids == ({"other"} if current_succeeds else {"owned"})
    assert solver.target_id == (None if current_succeeds else "owned")
    assert solver.target_ws_url == (
        None if current_succeeds else PAGE["webSocketDebuggerUrl"]
    )
    assert solver.current_target_url == (None if current_succeeds else PAGE["url"])


@pytest.mark.parametrize(
    "method", ["_open_target_tab", "_open_keepalive_tab", "_close_cdp_target"]
)
def test_lifecycle_transport_errors_do_not_log_private_request_url(
    monkeypatch, method, caplog
):
    def fail(*_a, **_k):
        raise requests.ConnectionError(
            "http://private-user:private-key@fixture/private-body"
        )

    monkeypatch.setattr("src.captcha_target.requests.get", fail)
    monkeypatch.setattr("src.captcha_target.requests.put", fail)
    solver = CaptchaSolver(target_url=PAGE["url"])
    args = ("owned",) if method == "_close_cdp_target" else ()
    assert not getattr(solver, method)(*args)
    assert "ConnectionError" in caplog.text
    assert "private-key" not in caplog.text
    assert "private-body" not in caplog.text

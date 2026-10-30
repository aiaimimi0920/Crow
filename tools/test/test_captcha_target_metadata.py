"""CDP metadata failures must not masquerade as an empty target directory."""

import time
from types import SimpleNamespace

import pytest

from src.captcha_budget import SolveBudget, SolveStopped
from src.captcha_solver import CaptchaSolver

TARGET = "https://sf-item.taobao.com/sf_item/123.htm"
PAGE = {
    "id": "bound",
    "type": "page",
    "url": TARGET,
    "webSocketDebuggerUrl": "ws://fixture/bound",
}


def response(payload, status=200):
    return SimpleNamespace(status_code=status, json=lambda: payload)


def stub_directory(monkeypatch, result):
    attempts = []

    def get(_url, *, timeout):
        attempts.append(timeout)
        return result

    monkeypatch.setattr("src.captcha_target.requests.get", get)
    return attempts


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_non_success_directory_response_is_unavailable(monkeypatch, caplog, status):
    attempts = stub_directory(
        monkeypatch, response({"error": "private-body-marker"}, status)
    )
    assert CaptchaSolver()._get_json("list") is None
    assert attempts == [2, 4, 6]
    assert "private-body-marker" not in caplog.text


@pytest.mark.parametrize(
    "payload",
    [
        {"error": "unavailable"},
        "unavailable",
        False,
        17,
        [None],
        ["page"],
        None,
    ],
)
def test_malformed_directory_never_reaches_target_selection(monkeypatch, payload):
    attempts = stub_directory(monkeypatch, response(payload))
    assert CaptchaSolver()._get_json("list") is None
    assert attempts == [2, 4, 6]


def test_transient_error_body_retries_before_using_valid_directory(monkeypatch):
    attempts = []
    replies = iter([response({"error": "unavailable"}), response([PAGE])])

    def get(_url, *, timeout):
        attempts.append(timeout)
        return next(replies)

    monkeypatch.setattr("src.captcha_target.requests.get", get)
    assert CaptchaSolver()._get_json("list") == [PAGE]
    assert attempts == [2, 4]


@pytest.mark.parametrize(
    "result", [response({"error": "unavailable"}), response([], 503)]
)
@pytest.mark.parametrize("has_bound_cache", [False, True])
def test_unavailable_directory_never_opens_a_duplicate_page(
    monkeypatch, result, has_bound_cache
):
    attempts = stub_directory(monkeypatch, result)
    solver = CaptchaSolver(target_url=TARGET)
    if has_bound_cache:
        solver._remember_target_tab(PAGE)
    connected = []
    monkeypatch.setattr(
        solver, "_connect_to_target", lambda ws, _title: connected.append(ws) or True
    )
    monkeypatch.setattr(
        solver,
        "_open_target_tab",
        lambda: pytest.fail("metadata failure opened a page"),
    )
    assert solver.connect_tab() is has_bound_cache
    assert connected == (["ws://fixture/bound"] if has_bound_cache else [])
    assert attempts == [2, 4, 6]


def test_empty_directory_is_valid_and_does_not_retry(monkeypatch):
    attempts = stub_directory(monkeypatch, response([]))
    assert CaptchaSolver()._get_json("list") == []
    assert attempts == [2]


def test_non_directory_json_contract_is_unchanged(monkeypatch):
    payload = {"Browser": "fixture"}
    attempts = stub_directory(monkeypatch, response(payload))
    assert CaptchaSolver()._get_json("version") == payload
    assert attempts == [2]


def test_invalid_directory_retry_still_obeys_cancellation(monkeypatch):
    attempts = stub_directory(monkeypatch, response({"error": "unavailable"}))
    solver = CaptchaSolver(cancel_checker=lambda: bool(attempts))
    solver._solve_budget = SolveBudget(deadline=time.monotonic() + 5)
    with pytest.raises(SolveStopped):
        solver._get_json("list")
    assert attempts == [2]
